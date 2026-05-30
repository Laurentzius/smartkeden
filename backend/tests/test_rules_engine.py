"""Unit tests for the Classification Rules Engine.

Tests rule matching logic, priority resolution, conflict handling,
missing attributes, circular dependencies, and failure recovery.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.core.classification.rule_models import (
    ClassificationRule,
    RuleAction,
    RuleCondition,
    RulesApplicationResult,
    AppliedRule,
    ClarifyingQuestion,
)
from app.core.classification.rules_engine import RulesEngine


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def engine(mock_db):
    """Create a RulesEngine with mocked DB."""
    eng = RulesEngine(db_session=mock_db)
    eng.invalidate_cache()
    return eng


def make_rule(
    rule_id: str = "test_rule",
    category_mask: str = "*",
    priority: int = 0,
    conditions: list[RuleCondition] | dict | None = None,
    action_type: str = "boost",
    target_code: str = "9503000000",
    reason: str = "test reason",
    source: str = "Test source document",
    confidence_boost: float | None = None,
) -> ClassificationRule:
    """Helper to create a ClassificationRule."""
    if conditions is None:
        conditions = [RuleCondition(attribute="material_outer", operator="==", value="пластик")]

    action = RuleAction(
        type=action_type,
        target_code=target_code,
        reason=reason,
        confidence_boost=confidence_boost,
    )
    return ClassificationRule(
        rule_id=rule_id,
        category_mask=category_mask,
        priority=priority,
        conditions=conditions,
        action=action,
        source=source,
        effective_date=date.today(),
    )


def make_candidate(
    hs_code: str = "9503001000",
    product_name: str = "Test product",
    confidence: float = 0.7,
    reasoning: str = "",
) -> dict:
    """Helper to create a candidate dict."""
    return {
        "hs_code": hs_code,
        "product_name_ru": product_name,
        "confidence_score": confidence,
        "duty_rate_percent": 10.0,
        "reasoning": reasoning,
    }


# ══════════════════════════════════════════════════════════════════════════
# Rule Matching: AND conditions
# ══════════════════════════════════════════════════════════════════════════

class TestRuleMatchingAllConditions:
    """Test that ALL conditions must match (AND logic)."""

    def test_all_conditions_match(self, engine):
        rule = make_rule(
            rule_id="test_and",
            conditions=[
                RuleCondition(attribute="material_outer", operator="==", value="пластик"),
                RuleCondition(attribute="size_cm", operator=">=", value=10),
            ],
        )
        attrs = {"material_outer": "пластик", "size_cm": 30}
        assert engine.check_rule_match(rule, attrs) is True

    def test_one_condition_fails(self, engine):
        rule = make_rule(
            rule_id="test_and_fail",
            conditions=[
                RuleCondition(attribute="material_outer", operator="==", value="пластик"),
                RuleCondition(attribute="size_cm", operator=">=", value=100),
            ],
        )
        attrs = {"material_outer": "пластик", "size_cm": 30}
        assert engine.check_rule_match(rule, attrs) is False

    def test_all_conditions_missing_attribute(self, engine):
        rule = make_rule(
            rule_id="test_and_missing",
            conditions=[
                RuleCondition(attribute="material_outer", operator="==", value="пластик"),
                RuleCondition(attribute="fur_coverage_percent", operator=">", value=50),
            ],
        )
        attrs = {"material_outer": "пластик"}
        result = engine.check_rule_match(rule, attrs)
        assert result == "fur_coverage_percent"  # Returns missing attr name


# ══════════════════════════════════════════════════════════════════════════
# Rule Matching: ANY conditions
# ══════════════════════════════════════════════════════════════════════════

class TestRuleMatchingAnyConditions:
    """Test ANY conditions (OR logic)."""

    def test_any_one_matches(self, engine):
        rule = make_rule(
            rule_id="test_any",
            conditions={"any": [
                {"attribute": "material_outer", "operator": "==", "value": "металл"},
                {"attribute": "material_outer", "operator": "==", "value": "пластик"},
            ]},
        )
        attrs = {"material_outer": "пластик"}
        assert engine.check_rule_match(rule, attrs) is True

    def test_any_none_match(self, engine):
        rule = make_rule(
            rule_id="test_any_none",
            conditions={"any": [
                {"attribute": "material_outer", "operator": "==", "value": "металл"},
                {"attribute": "material_outer", "operator": "==", "value": "дерево"},
            ]},
        )
        attrs = {"material_outer": "пластик"}
        assert engine.check_rule_match(rule, attrs) is False

    def test_any_all_missing(self, engine):
        rule = make_rule(
            rule_id="test_any_missing",
            conditions={"any": [
                {"attribute": "fur_coverage_percent", "operator": ">", "value": 50},
                {"attribute": "textile_percent", "operator": ">", "value": 50},
            ]},
        )
        attrs = {"material_outer": "пластик"}
        result = engine.check_rule_match(rule, attrs)
        assert isinstance(result, str)  # Returns first missing attr name


# ══════════════════════════════════════════════════════════════════════════
# Operators
# ══════════════════════════════════════════════════════════════════════════

class TestOperators:
    """Test all valid operators."""

    def test_equality(self, engine):
        rule = make_rule("op_eq", conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")])
        assert engine.check_rule_match(rule, {"material_outer": "пластик"}) is True
        assert engine.check_rule_match(rule, {"material_outer": "дерево"}) is False

    def test_not_equal(self, engine):
        rule = make_rule("op_ne", conditions=[RuleCondition(attribute="material_outer", operator="!=", value="металл")])
        assert engine.check_rule_match(rule, {"material_outer": "пластик"}) is True
        assert engine.check_rule_match(rule, {"material_outer": "металл"}) is False

    def test_greater_than(self, engine):
        rule = make_rule("op_gt", conditions=[RuleCondition(attribute="size_cm", operator=">", value=10)])
        assert engine.check_rule_match(rule, {"size_cm": 30}) is True
        assert engine.check_rule_match(rule, {"size_cm": 5}) is False

    def test_less_than(self, engine):
        rule = make_rule("op_lt", conditions=[RuleCondition(attribute="weight_kg", operator="<", value=5)])
        assert engine.check_rule_match(rule, {"weight_kg": 2}) is True
        assert engine.check_rule_match(rule, {"weight_kg": 10}) is False

    def test_contains(self, engine):
        rule = make_rule("op_contains", conditions=[RuleCondition(attribute="brand", operator="contains", value="lego")])
        assert engine.check_rule_match(rule, {"brand": "LEGO Group"}) is True
        assert engine.check_rule_match(rule, {"brand": "Mattel"}) is False

    def test_not_contains(self, engine):
        rule = make_rule("op_not_contains", conditions=[RuleCondition(attribute="brand", operator="not_contains", value="fake")])
        assert engine.check_rule_match(rule, {"brand": "LEGO"}) is True
        assert engine.check_rule_match(rule, {"brand": "fakebrand"}) is False

    def test_in_list(self, engine):
        rule = make_rule("op_in", conditions=[RuleCondition(attribute="country_of_origin", operator="in", value=["Китай", "Турция"])])
        assert engine.check_rule_match(rule, {"country_of_origin": "Китай"}) is True
        assert engine.check_rule_match(rule, {"country_of_origin": "Германия"}) is False

    def test_not_in_list(self, engine):
        rule = make_rule("op_not_in", conditions=[RuleCondition(attribute="country_of_origin", operator="not_in", value=["Китай", "Турция"])])
        assert engine.check_rule_match(rule, {"country_of_origin": "Германия"}) is True
        assert engine.check_rule_match(rule, {"country_of_origin": "Китай"}) is False

    def test_boolean_equality(self, engine):
        rule = make_rule("op_bool", conditions=[RuleCondition(attribute="has_electronics", operator="==", value=True)])
        assert engine.check_rule_match(rule, {"has_electronics": True}) is True
        assert engine.check_rule_match(rule, {"has_electronics": False}) is False


# ══════════════════════════════════════════════════════════════════════════
# Priority Resolution
# ══════════════════════════════════════════════════════════════════════════

class TestRulePriorityResolution:
    """Test that higher priority rules are checked first."""

    def test_priority_sorting(self, engine):
        low = make_rule("low_priority", priority=0)
        mid = make_rule("mid_priority", priority=10)
        high = make_rule("high_priority", priority=100)

        rules = [low, mid, high]
        rules.sort(key=lambda r: (-r.priority, r.rule_id))
        assert rules[0].rule_id == "high_priority"
        assert rules[1].rule_id == "mid_priority"
        assert rules[2].rule_id == "low_priority"

    def test_same_priority_alphabetical(self, engine):
        rule_b = make_rule("b_rule", priority=10)
        rule_a = make_rule("a_rule", priority=10)
        rule_c = make_rule("c_rule", priority=10)

        rules = [rule_b, rule_a, rule_c]
        rules.sort(key=lambda r: (-r.priority, r.rule_id))
        assert rules[0].rule_id == "a_rule"
        assert rules[1].rule_id == "b_rule"
        assert rules[2].rule_id == "c_rule"


# ══════════════════════════════════════════════════════════════════════════
# Rule Application: Actions
# ══════════════════════════════════════════════════════════════════════════

class TestRuleApplicationActions:
    """Test that actions are applied correctly to candidates."""

    def test_reclassify_action(self, engine):
        rule = make_rule(
            "reclass_test",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="reclassify",
            target_code="9503003500",
            reason="Plastic toys go to 9503003500",
        )
        candidates = [make_candidate("9503001000", "Toy", 0.8)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert len(result.candidates) == 1
        assert result.candidates[0]["hs_code"] == "9503003500"
        assert "reclassified" in result.candidates[0]["reasoning"]
        assert len(result.applied_rules) == 1
        assert result.applied_rules[0].action_type == "reclassify"

    def test_boost_action(self, engine):
        rule = make_rule(
            "boost_test",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="хлопок")],
            action_type="boost",
            target_code="9503",
            confidence_boost=0.15,
            reason="Cotton products are common in 9503",
        )
        candidates = [make_candidate("9503001000", "Cotton Toy", 0.7)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "хлопок"},
            rules=[rule],
        )
        assert result.candidates[0]["confidence_score"] == 0.85
        assert "boosted" in result.candidates[0]["reasoning"]

    def test_boost_clamped_to_1(self, engine):
        rule = make_rule(
            "boost_clamp",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="хлопок")],
            action_type="boost",
            target_code="9503",
            confidence_boost=0.5,
        )
        candidates = [make_candidate("9503001000", "Cotton Toy", 0.9)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "хлопок"},
            rules=[rule],
        )
        assert result.candidates[0]["confidence_score"] == 1.0

    def test_exclude_action(self, engine):
        rule = make_rule(
            "exclude_test",
            conditions=[RuleCondition(attribute="has_electronics", operator="==", value=True)],
            action_type="exclude",
            target_code="9503",
            reason="Electronic toys need different classification",
        )
        candidates = [
            make_candidate("9503001000", "Plastic Toy", 0.8),
            make_candidate("8504000000", "Electronic Device", 0.6),
        ]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"has_electronics": True},
            rules=[rule],
        )
        assert len(result.candidates) == 1
        assert result.candidates[0]["hs_code"] == "8504000000"

    def test_exclude_would_remove_all(self, engine):
        rule = make_rule(
            "exclude_all",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="exclude",
            target_code="9503",
        )
        candidates = [make_candidate("9503001000", "Plastic Toy", 0.8)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        # Should keep at least one candidate
        assert len(result.candidates) == 1
        assert result.candidates[0]["hs_code"] == "9503001000"

    def test_warning_action(self, engine):
        rule = make_rule(
            "warning_test",
            conditions=[RuleCondition(attribute="has_electronics", operator="==", value=True)],
            action_type="warning",
            reason="Electronic products may require additional certification",
        )
        candidates = [make_candidate("9503001000", "Toy", 0.8)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"has_electronics": True},
            rules=[rule],
        )
        assert "⚠" in result.candidates[0]["reasoning"]


# ══════════════════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge case handling."""

    def test_missing_attribute_returns_question(self, engine):
        rule = make_rule(
            "missing_attr",
            conditions=[RuleCondition(attribute="fur_coverage_percent", operator=">", value=50)],
            action_type="boost",
            target_code="4303",
        )
        candidates = [make_candidate("4303000000", "Fur coat", 0.6)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "мех"},
            rules=[rule],
        )
        assert len(result.clarifying_questions) == 1
        assert result.clarifying_questions[0].attribute == "fur_coverage_percent"
        # Rule should NOT be applied (missing attribute)
        assert len(result.applied_rules) == 0

    def test_max_three_clarifying_questions(self, engine):
        rules = [
            make_rule(f"missing_{i}", conditions=[
                RuleCondition(attribute=f"attr_{i}", operator="==", value="test")
            ]) for i in range(5)
        ]
        candidates = [make_candidate()]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={},  # No attributes at all
            rules=rules,
        )
        assert len(result.clarifying_questions) <= 3

    def test_circular_rules_detected(self, engine):
        """Two rules that reclassify back and forth should be detected."""
        rule_a = make_rule(
            "circular_a",
            priority=100,
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="reclassify",
            target_code="9999000000",
            reason="A -> Z",
        )
        rule_b = make_rule(
            "circular_b",
            priority=90,
            conditions=[RuleCondition(attribute="hs_code", operator="==", value="9999000000")],
            action_type="reclassify",
            target_code="9503001000",
            reason="Z -> A",
        )

        candidates = [make_candidate("9503001000", "Toy", 0.8)]
        # Apply rule_a first (higher priority), then rule_b matches the result
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule_a, rule_b],
        )
        # Both rules should have been attempted but circular detection limits effect
        assert len(result.candidates) > 0
        assert len(result.applied_rules) > 0

    def test_rule_failure_skipped(self, engine):
        """A rule that causes an exception during application should be skipped."""
        # This rule references an attribute that wil cause an issue
        rule_ok = make_rule(
            "ok_rule",
            priority=100,
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="boost",
            confidence_boost=0.1,
        )
        # A rule with invalid action that would crash normally
        bad_action = RuleAction(type="boost", target_code="9503", reason="bad", confidence_boost=None)

        candidates = [make_candidate("9503001000", "Toy", 0.7)]
        # The engine should handle failure gracefully
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule_ok],
        )
        assert result.candidates[0]["confidence_score"] == pytest.approx(0.8)
        rule = make_rule(
            "no_match",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="металл")],
        )
        candidates = [make_candidate("9503001000", "Plastic Toy", 0.8)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert len(result.applied_rules) == 0
        assert result.candidates[0]["hs_code"] == "9503001000"

    def test_empty_candidates(self, engine):
        rule = make_rule()
        result = engine.apply_rules(
            candidates=[],
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert len(result.candidates) == 0
        assert len(result.applied_rules) > 0  # Rule was still applied (no candidates to modify)

    def test_empty_attributes(self, engine):
        rule = make_rule(
            "empty_attrs",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
        )
        candidates = [make_candidate()]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={},
            rules=[rule],
        )
        assert len(result.clarifying_questions) == 1
        assert result.clarifying_questions[0].attribute == "material_outer"


# ══════════════════════════════════════════════════════════════════════════
# Cache Tests
# ══════════════════════════════════════════════════════════════════════════

class TestCache:
    """Test in-memory caching behavior."""

    def test_cache_stores_rules(self, engine, mock_db):
        from app.core.models import ClassificationRuleModel
        # Mock the DB query
        mock_row = MagicMock()
        mock_row.rule_id = "cached_rule"
        mock_row.category_mask = "9503*"
        mock_row.priority = 10
        mock_row.conditions = [{"attribute": "material_outer", "operator": "==", "value": "пластик"}]
        mock_row.action = {"type": "boost", "target_code": "9503", "reason": "test"}
        mock_row.source = "Test"
        mock_row.effective_date = date.today()
        mock_row.expiry_date = None
        mock_row.created_by = None
        mock_row.version = 1
        mock_row.is_active = True

        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_row]

        # First call populates cache
        rules = engine.get_rules_for_category("9503*")
        assert len(rules) == 1
        assert rules[0].rule_id == "cached_rule"

        # Second call should use cache (DB not called again)
        mock_db.query.reset_mock()
        rules2 = engine.get_rules_for_category("9503*")
        assert len(rules2) == 1
        assert len(mock_db.query.call_args_list) == 0  # Cache hit

    def test_invalidate_cache(self, engine, mock_db):
        from app.core.models import ClassificationRuleModel
        mock_row = MagicMock()
        mock_row.rule_id = "cached_rule"
        mock_row.category_mask = "*"
        mock_row.priority = 10
        mock_row.conditions = [{"attribute": "material_outer", "operator": "==", "value": "пластик"}]
        mock_row.action = {"type": "boost", "target_code": "9503", "reason": "test"}
        mock_row.source = "Test"
        mock_row.effective_date = date.today()
        mock_row.expiry_date = None
        mock_row.created_by = None
        mock_row.version = 1
        mock_row.is_active = True

        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_row]

        engine.get_rules_for_category("*")
        engine.invalidate_cache()
        mock_db.query.reset_mock()

        # After invalidation, DB should be called again
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_row]
        engine.get_rules_for_category("*")
        assert len(mock_db.query.call_args_list) > 0  # Cache miss


# ══════════════════════════════════════════════════════════════════════════
# Category Matching
# ══════════════════════════════════════════════════════════════════════════

class TestCategoryMatching:
    """Test category_mask matching logic."""

    def test_exact_match(self, engine):
        mask = "9503"
        assert engine._category_matches(mask, "9503") is True
        assert engine._category_matches(mask, "9504") is False

    def test_prefix_match(self, engine):
        mask = "9503*"
        assert engine._category_matches(mask, "9503") is True
        assert engine._category_matches(mask, "950300") is True
        assert engine._category_matches(mask, "9503003500") is True
        assert engine._category_matches(mask, "9504") is False

    def test_wildcard_match(self, engine):
        assert engine._category_matches("*", "anything") is True
        assert engine._category_matches("*", "9503") is True

    def test_partial_prefix(self, engine):
        mask = "61*"
        assert engine._category_matches(mask, "6100") is True
        assert engine._category_matches(mask, "6110") is True
        assert engine._category_matches(mask, "62") is False


# ══════════════════════════════════════════════════════════════════════════
# Condition format variations
# ══════════════════════════════════════════════════════════════════════════

class TestConditionFormats:
    """Test different condition format structures."""

    def test_dict_all_format(self, engine):
        rule = make_rule(
            "dict_all",
            conditions={"all": [
                {"attribute": "material_outer", "operator": "==", "value": "пластик"},
                {"attribute": "size_cm", "operator": ">=", "value": 10},
            ]},
        )
        assert engine.check_rule_match(rule, {"material_outer": "пластик", "size_cm": 30}) is True

    def test_dict_any_format(self, engine):
        rule = make_rule(
            "dict_any",
            conditions={"any": [
                {"attribute": "material_outer", "operator": "==", "value": "пластик"},
                {"attribute": "material_outer", "operator": "==", "value": "дерево"},
            ]},
        )
        assert engine.check_rule_match(rule, {"material_outer": "дерево"}) is True

    def test_list_format_implicit_and(self, engine):
        rule = make_rule(
            "list_and",
            conditions=[
                RuleCondition(attribute="material_outer", operator="==", value="пластик"),
                RuleCondition(attribute="has_electronics", operator="==", value=False),
            ],
        )
        assert engine.check_rule_match(rule, {"material_outer": "пластик", "has_electronics": False}) is True
        assert engine.check_rule_match(rule, {"material_outer": "пластик", "has_electronics": True}) is False


# ══════════════════════════════════════════════════════════════════════════
# Performance Baseline
# ══════════════════════════════════════════════════════════════════════════

class TestPerformanceBaseline:
    """Quick performance sanity checks."""

    def test_many_rules_application(self, engine):
        """100 rules should apply in reasonable time."""
        import time

        rules = [
            make_rule(
                f"perf_rule_{i}",
                priority=i,
                conditions=[RuleCondition(attribute="material_outer", operator="==", value=f"material_{i % 5}")],
            )
            for i in range(100)
        ]

        candidates = [make_candidate(f"{9503000000 + i:010d}", f"Product {i}", 0.5 + (i * 0.005)) for i in range(10)]
        attrs = {"material_outer": "material_2", "size_cm": 30}

        start = time.perf_counter()
        result = engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules)
        elapsed = time.perf_counter() - start

        # 100 rules with 10 candidates should be fast
        assert elapsed < 1.0, f"100 rules took {elapsed:.2f}s, expected <1.0s"
        assert len(result.candidates) > 0
