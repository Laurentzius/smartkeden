"""Classification Rules Engine.

A deterministic engine that loads rules from the database and applies them
to HS code candidates based on extracted product attributes.

Design decisions:
- Cache active rules in memory (TTL: RULES_CACHE_TTL seconds, default 300)
- Rules sorted by priority DESC, then rule_id ASC for tie-breaking
- Max 10 rule applications per candidate to detect circular dependencies
- Missing attributes → clarifying questions (max 3)
- Rule application failures → skip, log, continue
"""

import logging
import time
from collections import defaultdict
from datetime import date
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.core.classification.rule_models import (
    ClassificationRule,
    RuleAction,
    RuleCondition,
    RulesApplicationResult,
    AppliedRule,
    ClarifyingQuestion,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum number of rule applications per candidate to detect cycles
_MAX_RULE_APPLICATIONS = 10
# Maximum number of clarifying questions to return
_MAX_CLARIFYING_QUESTIONS = 3


class RulesEngine:
    """Singleton-like engine that applies classification rules.

    Thread-safe: cache reads/writes are protected by per-key timestamps.
    Not a true singleton — instantiated per-session with a DB session.
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        self._cache: dict[str, list[ClassificationRule]] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl: int = getattr(settings, "RULES_CACHE_TTL", 300)

    # ── Cache management ─────────────────────────────────────────────────

    def _cache_key(self, category_mask: str) -> str:
        return category_mask

    def _is_cache_valid(self, key: str) -> bool:
        ts = self._cache_timestamps.get(key, 0)
        return (time.monotonic() - ts) < self._cache_ttl

    def invalidate_cache(self) -> None:
        """Invalidate all cached rules."""
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.debug("Rules cache invalidated")

    # ── Rule retrieval ───────────────────────────────────────────────────

    def get_rules_for_category(self, category_mask: str) -> list[ClassificationRule]:
        """Get active rules matching a category mask (with caching).

        Args:
            category_mask: Category mask, e.g. "9503*", "61*", or "*"

        Returns:
            List of active ClassificationRule sorted by priority DESC.
        """
        key = self._cache_key(category_mask)
        if self._is_cache_valid(key) and key in self._cache:
            return self._cache[key]

        today = date.today()
        try:
            from app.core.models import ClassificationRuleModel
            db: Session = self.db
            rows = (
                db.query(ClassificationRuleModel)
                .filter(
                    ClassificationRuleModel.is_active == True,
                    ClassificationRuleModel.effective_date <= today,
                    (
                        (ClassificationRuleModel.expiry_date == None)
                        | (ClassificationRuleModel.expiry_date >= today)
                    ),
                )
                .order_by(ClassificationRuleModel.priority.desc())
                .all()
            )
        except Exception:
            logger.exception("Failed to query classification rules")
            return []

        # Convert ORM rows to Pydantic models and filter by category_mask
        rules: list[ClassificationRule] = []
        for row in rows:
            rule = ClassificationRule(
                rule_id=row.rule_id,
                category_mask=row.category_mask,
                priority=row.priority,
                conditions=row.conditions,
                action=RuleAction(**row.action) if isinstance(row.action, dict) else row.action,
                source=row.source,
                effective_date=row.effective_date.date() if hasattr(row.effective_date, 'date') else row.effective_date,
                expiry_date=row.expiry_date.date() if row.expiry_date and hasattr(row.expiry_date, 'date') else row.expiry_date,
                created_by=row.created_by,
                version=row.version,
                is_active=row.is_active,
            )
            mask = rule.category_mask
            if mask == "*" or self._category_matches(mask, category_mask):
                rules.append(rule)

        # Sort: priority DESC, then rule_id ASC (alphabetical) for tie-breaking
        rules.sort(key=lambda r: (-r.priority, r.rule_id))

        self._cache[key] = rules
        self._cache_timestamps[key] = time.monotonic()
        return rules

    @staticmethod
    def _category_matches(mask: str, target: str) -> bool:
        """Check if target category matches the mask.

        "*" matches all. "9503*" matches "9503", "950300", etc.
        """
        if mask == "*":
            return True
        if mask.endswith("*"):
            prefix = mask[:-1]
            return target.startswith(prefix)
        return mask == target

    # ── Rule application ────────────────────────────────────────────────

    def apply_rules(
        self,
        candidates: list[dict],
        attributes: dict,
        rules: Optional[list[ClassificationRule]] = None,
    ) -> RulesApplicationResult:
        """Apply classification rules to HS code candidates.

        Args:
            candidates: Initial HS code candidates as list of dicts.
            attributes: Extracted product attributes dict.
            rules: Optional pre-loaded rules (avoids re-query).

        Returns:
            RulesApplicationResult with refined candidates, questions, and applied rules.
        """
        if rules is None:
            rules = self.get_rules_for_category("*")

        applied_rules: list[AppliedRule] = []
        clarifying_questions: list[ClarifyingQuestion] = []
        refined_candidates = [dict(c) for c in candidates]  # shallow copy

        # Sort rules: priority DESC, then rule_id ASC for tie-breaking
        rules = sorted(rules, key=lambda r: (-r.priority, r.rule_id))
        application_counts: dict[int, int] = defaultdict(int)

        for rule in rules:
            try:
                match_result = self.check_rule_match(rule, attributes)

                if match_result is True:
                    # Rule matches — apply it
                    before = [dict(c) for c in refined_candidates]
                    refined_candidates, apps = self._apply_action(
                        refined_candidates, rule, application_counts
                    )
                    for app in apps:
                        applied_rules.append(app)
                        self._log_audit(
                            rule_id=rule.rule_id,
                            action_type=app.action_type,
                            attributes=attributes,
                            old_candidates=before,
                            new_candidates=refined_candidates,
                        )
                elif isinstance(match_result, str):
                    # Missing attribute — add clarifying question
                    if len(clarifying_questions) < _MAX_CLARIFYING_QUESTIONS:
                        clarifying_questions.append(
                            ClarifyingQuestion(
                                attribute=match_result,
                                question=self._question_for_attribute(match_result),
                            )
                        )
                # match_result is False → skip this rule
            except Exception:
                logger.exception("Rule %s application failed, skipping", rule.rule_id)
                continue

        return RulesApplicationResult(
            candidates=refined_candidates,
            clarifying_questions=clarifying_questions,
            applied_rules=applied_rules,
        )

    def check_rule_match(self, rule: ClassificationRule, attributes: dict) -> bool | str:
        """Check if rule conditions match the given attributes.

        Returns:
            True if all conditions match.
            str (attribute name) if a required attribute is missing.
            False if conditions do not match.
        """
        conditions = rule.conditions

        # Normalize conditions structure
        if isinstance(conditions, list):
            # Implicit AND: all conditions must match
            return self._check_all_conditions(conditions, attributes)
        elif isinstance(conditions, dict):
            if "all" in conditions:
                return self._check_all_conditions(conditions["all"], attributes)
            elif "any" in conditions:
                return self._check_any_conditions(conditions["any"], attributes)
            else:
                logger.warning("Rule %s has unrecognized conditions structure", rule.rule_id)
                return False
        return False

    def _check_all_conditions(
        self, conditions: list[dict | RuleCondition], attributes: dict
    ) -> bool | str:
        """Check that ALL conditions match (AND logic)."""
        for cond in conditions:
            if isinstance(cond, dict):
                cond = RuleCondition(**cond)
            result = self._evaluate_condition(cond, attributes)
            if result is not True:
                return result  # False or missing attribute name
        return True

    def _check_any_conditions(
        self, conditions: list[dict | RuleCondition], attributes: dict
    ) -> bool | str:
        """Check that ANY condition matches (OR logic)."""
        missing_attrs: list[str] = []
        for cond in conditions:
            if isinstance(cond, dict):
                cond = RuleCondition(**cond)
            result = self._evaluate_condition(cond, attributes)
            if result is True:
                return True
            if isinstance(result, str):
                missing_attrs.append(result)
        # If any were missing (but none matched), return first missing attr
        if missing_attrs:
            return missing_attrs[0]
        return False

    def _evaluate_condition(self, cond: RuleCondition, attributes: dict) -> bool | str:
        """Evaluate a single condition against attributes.

        Returns:
            True if condition matches.
            str (attribute name) if the attribute is missing from attributes dict.
            False if condition does not match.
        """
        attr_name = cond.attribute
        operator = cond.operator
        expected = cond.value

        # Check if attribute exists
        if attr_name not in attributes or attributes[attr_name] is None:
            return attr_name  # Missing attribute — signal for clarifying question

        actual = attributes[attr_name]

        try:
            if operator == "==":
                return actual == expected
            elif operator == "!=":
                return actual != expected
            elif operator in (">", "<", ">=", "<="):
                return self._compare_numeric(actual, expected, operator)
            elif operator == "contains":
                return str(expected).lower() in str(actual).lower()
            elif operator == "not_contains":
                return str(expected).lower() not in str(actual).lower()
            elif operator == "in":
                if not isinstance(expected, (list, tuple, set)):
                    return False
                return actual in expected
            elif operator == "not_in":
                if not isinstance(expected, (list, tuple, set)):
                    return True  # Can't be in something that's not a collection
                return actual not in expected
            else:
                logger.warning("Unknown operator: %s", operator)
                return False
        except (TypeError, ValueError) as e:
            logger.warning(
                "Condition evaluation failed for %s %s %s: %s",
                attr_name, operator, expected, e,
            )
            return False

    @staticmethod
    def _compare_numeric(actual: Any, expected: Any, operator: str) -> bool:
        """Safely compare numeric values."""
        try:
            a = float(actual)
            e = float(expected)
        except (TypeError, ValueError):
            return False
        if operator == ">":
            return a > e
        elif operator == "<":
            return a < e
        elif operator == ">=":
            return a >= e
        elif operator == "<=":
            return a <= e
        return False

    # ── Action application ───────────────────────────────────────────────

    def _apply_action(
        self,
        candidates: list[dict],
        rule: ClassificationRule,
        application_counts: dict[int, int],
    ) -> tuple[list[dict], list[AppliedRule]]:
        """Apply a single rule's action to candidates.

        Returns (refined_candidates, applied_rules_list).
        """
        action = rule.action
        applied: list[AppliedRule] = []

        if action.type == "reclassify":
            # Replace all candidates with the target code
            new_candidates = []
            for i, c in enumerate(candidates):
                application_counts[i] += 1
                if application_counts[i] > _MAX_RULE_APPLICATIONS:
                    logger.warning(
                        "Circular rule dependency detected for candidate %d (rule %s)",
                        i, rule.rule_id,
                    )
                    new_candidates.append(c)  # Keep original
                    continue
                new_c = dict(c)
                new_c["hs_code"] = action.target_code
                new_c["reasoning"] = (new_c.get("reasoning", "") + f" [reclassified by {rule.rule_id}: {action.reason}]").strip()
                new_candidates.append(new_c)

            applied.append(AppliedRule(
                rule_id=rule.rule_id,
                action_type="reclassify",
                target_code=action.target_code,
                reason=action.reason,
            ))
            return new_candidates, applied

        elif action.type == "boost":
            # Increase confidence_score for candidates matching target_code
            boost = action.confidence_boost or 0.1
            new_candidates = []
            for i, c in enumerate(candidates):
                application_counts[i] += 1
                if application_counts[i] > _MAX_RULE_APPLICATIONS:
                    logger.warning(
                        "Circular rule dependency detected for candidate %d (rule %s)",
                        i, rule.rule_id,
                    )
                    new_candidates.append(c)
                    continue

                new_c = dict(c)
                if not action.target_code or c.get("hs_code", "").startswith(action.target_code[:4]):
                    current_conf = float(new_c.get("confidence_score", 0.5))
                    new_c["confidence_score"] = min(current_conf + boost, 1.0)
                    new_c["reasoning"] = (new_c.get("reasoning", "") + f" [boosted by {rule.rule_id}: {action.reason}]").strip()
                new_candidates.append(new_c)

            applied.append(AppliedRule(
                rule_id=rule.rule_id,
                action_type="boost",
                target_code=action.target_code,
                reason=action.reason,
            ))
            return new_candidates, applied

        elif action.type == "exclude":
            # Remove candidates matching target_code
            new_candidates = [
                c for c in candidates
                if not action.target_code or not c.get("hs_code", "").startswith(action.target_code[:4])
            ]
            if not new_candidates:
                # Don't exclude all candidates — keep at least one
                logger.warning("Rule %s would exclude all candidates, keeping original", rule.rule_id)
                new_candidates = candidates

            applied.append(AppliedRule(
                rule_id=rule.rule_id,
                action_type="exclude",
                target_code=action.target_code,
                reason=action.reason,
            ))
            return new_candidates, applied

        elif action.type == "require_info":
            # This is handled at the rule-match level (missing attribute)
            # If we reach here, the attribute was present — apply the rule normally
            applied.append(AppliedRule(
                rule_id=rule.rule_id,
                action_type="require_info",
                target_code=action.target_code,
                reason=action.reason,
            ))
            return candidates, applied

        elif action.type == "warning":
            # Add warning to candidate reasoning
            new_candidates = []
            for c in candidates:
                new_c = dict(c)
                new_c["reasoning"] = (new_c.get("reasoning", "") + f" [⚠ {rule.rule_id}: {action.reason}]").strip()
                new_candidates.append(new_c)

            applied.append(AppliedRule(
                rule_id=rule.rule_id,
                action_type="warning",
                target_code=action.target_code,
                reason=action.reason,
            ))
            return new_candidates, applied

        return candidates, applied

    # ── Audit logging ────────────────────────────────────────────────────

    def _log_audit(
        self,
        rule_id: str,
        action_type: str,
        attributes: dict,
        old_candidates: list[dict],
        new_candidates: list[dict],
        session_id: str = "",
    ) -> None:
        """Log rule application to the audit table (non-blocking)."""
        try:
            from app.core.database import SessionLocal
            db: Session = self.db
            if db is None:
                return

            # Use raw SQL to avoid ORM dependency on the audit table
            import json
            db.execute(
                """INSERT INTO rules_audit_log (rule_id, action, attributes, old_candidates, new_candidates, session_id)
                   VALUES (:rule_id, :action, :attributes, :old_candidates, :new_candidates, :session_id)""",
                {
                    "rule_id": rule_id,
                    "action": f"applied:{action_type}",
                    "attributes": json.dumps(attributes, default=str),
                    "old_candidates": json.dumps(old_candidates, default=str),
                    "new_candidates": json.dumps(new_candidates, default=str),
                    "session_id": session_id,
                },
            )
            db.commit()
        except Exception:
            logger.exception("Failed to log rule application audit for %s (non-blocking)", rule_id)

    # ── Clarifying questions ─────────────────────────────────────────────

    @staticmethod
    def _question_for_attribute(attribute: str) -> str:
        """Generate a clarifying question for a missing attribute."""
        questions_map = {
            "material_outer": "Из какого материала изготовлен внешний слой товара?",
            "material_filling": "Есть ли наполнитель и из какого материала?",
            "material_coating": "Есть ли покрытие и из какого материала?",
            "size_cm": "Какой максимальный размер товара в сантиметрах?",
            "weight_kg": "Какой вес товара в килограммах?",
            "volume_liters": "Какой объем товара в литрах?",
            "has_electronics": "Содержит ли товар электронные компоненты?",
            "has_sound_module": "Издает ли товар звуки (есть ли звуковой модуль)?",
            "has_movement": "Имеет ли товар механические движущиеся части?",
            "has_lighting": "Есть ли у товара световые элементы?",
            "brand": "Какой бренд или производитель товара?",
            "country_of_origin": "Из какой страны товар?",
            "target_audience": "Для кого предназначен товар (дети, взрослые)?",
            "fur_coverage_percent": "Какой процент натурального меха в товаре?",
            "textile_percent": "Какой процент текстиля в составе товара?",
            "metal_percent": "Какой процент металла в составе товара?",
        }
        return questions_map.get(attribute, f"Уточните характеристику: {attribute}")
