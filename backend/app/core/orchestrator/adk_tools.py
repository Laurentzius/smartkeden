"""ADK Tools for the Classification Rules Engine.

Provides tools that can be called from ADK workflow nodes to apply
classification rules during the HS code classification pipeline.

Design decisions:
- Tools are async functions that accept ADK context for state management
- Rules Engine is obtained from wiring (singleton pattern)
- Session state (extracted_attributes, applied_rules, missing_attributes)
  is stored in ctx.state for multi-turn workflows
"""

import logging
from typing import Any

from app.core.classification.rule_models import RulesApplicationResult

logger = logging.getLogger(__name__)


async def apply_classification_rules(
    ctx: Any,
    candidates: list[dict],
    attributes: dict,
) -> dict:
    """Apply classification rules to refine HS code candidates.

    Called from hs_classifier_node in the ADK workflow.

    Args:
        ctx: ADK context (provides access to session state via ctx.state).
        candidates: Initial HS code candidates from HSCodeClassifier.
        attributes: Extracted product attributes dict.

    Returns:
        Dict with keys:
            candidates: Refined HS code candidates
            clarifying_questions: Questions if attributes are missing
            applied_rules: List of rules that were applied
    """
    from app.core.database import SessionLocal
    from app.core.classification.rules_engine import RulesEngine

    db = SessionLocal()

    try:
        rules_engine = RulesEngine(db_session=db)

        # Load rules for candidate categories
        category_masks = set()
        for c in candidates:
            hs_code = c.get("hs_code", "")
            if len(hs_code) >= 4:
                category_masks.add(hs_code[:4] + "*")
            elif hs_code:
                category_masks.add(hs_code + "*")

        # Also include wildcard rule
        category_masks.add("*")

        # Aggregate rules from all relevant categories
        all_rules = []
        seen_ids = set()
        for mask in category_masks:
            for rule in rules_engine.get_rules_for_category(mask):
                if rule.rule_id not in seen_ids:
                    all_rules.append(rule)
                    seen_ids.add(rule.rule_id)

        # Sort: priority DESC, then rule_id ASC
        all_rules.sort(key=lambda r: (-r.priority, r.rule_id))

        # Apply rules
        result: RulesApplicationResult = rules_engine.apply_rules(
            candidates=candidates,
            attributes=attributes,
            rules=all_rules,
        )

        # Store in ADK session state
        if hasattr(ctx, "state") and ctx.state is not None:
            ctx.state["extracted_attributes"] = attributes
            ctx.state["applied_rules"] = [r.model_dump() for r in result.applied_rules]

            if result.clarifying_questions:
                ctx.state["missing_attributes"] = [
                    q.model_dump() for q in result.clarifying_questions
                ]

        return result.model_dump()

    except Exception as e:
        logger.exception("apply_classification_rules failed: %s", e)
        # Return original candidates on failure (graceful degradation)
        return {
            "candidates": candidates,
            "clarifying_questions": [],
            "applied_rules": [],
        }
    finally:
        db.close()
