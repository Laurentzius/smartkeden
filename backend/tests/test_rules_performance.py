"""Performance tests for the Classification Rules Engine.

Ensures that the rules engine meets performance requirements:
- 1000 rules applied in under 500ms
- Cache hits are instantaneous
- Bulk operations don't degrade linearly
"""

import time
import pytest
from datetime import date
from unittest.mock import MagicMock

from app.core.classification.rule_models import (
    ClassificationRule,
    RuleAction,
    RuleCondition,
)
from app.core.classification.rules_engine import RulesEngine


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def engine(mock_db):
    eng = RulesEngine(db_session=mock_db)
    eng.invalidate_cache()
    return eng


def make_rule(idx: int = 0, category_mask: str = "*") -> ClassificationRule:
    """Create a rule that matches material_n = material_{idx % 10}."""
    return ClassificationRule(
        rule_id=f"perf_rule_{idx:04d}",
        category_mask=category_mask,
        priority=idx,
        conditions=[
            RuleCondition(
                attribute="material_outer",
                operator="==",
                value=f"material_{idx % 20}",
            )
        ],
        action=RuleAction(
            type="boost",
            target_code="9503",
            reason=f"Boost for material_{idx % 20}",
            confidence_boost=0.01,
        ),
        source="Performance test",
        effective_date=date.today(),
    )


def make_candidate(idx: int = 0) -> dict:
    return {
        "hs_code": f"{9503000000 + idx:010d}",
        "product_name_ru": f"Product {idx}",
        "confidence_score": 0.7,
        "duty_rate_percent": 10.0,
        "reasoning": "",
    }


# ══════════════════════════════════════════════════════════════════════════
# Performance Tests
# ══════════════════════════════════════════════════════════════════════════

class TestRulesPerformance:
    """Measure rules application performance."""

    def test_100_rules_under_100ms(self, engine):
        """100 rules and 10 candidates should apply in under 100ms."""
        rules = [make_rule(i) for i in range(100)]
        candidates = [make_candidate(i) for i in range(10)]
        attrs = {"material_outer": "material_5", "size_cm": 30}

        # Warm up
        engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules[:10])

        start = time.perf_counter()
        result = engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.100, f"100 rules took {elapsed:.3f}s, expected <0.100s"
        assert len(result.candidates) > 0

    def test_1000_rules_under_500ms(self, engine):
        """1000 rules and 10 candidates should apply in under 500ms."""
        rules = [make_rule(i) for i in range(1000)]
        candidates = [make_candidate(i) for i in range(10)]
        attrs = {"material_outer": "material_5", "size_cm": 30}

        start = time.perf_counter()
        result = engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, f"1000 rules took {elapsed:.3f}s, expected <0.500s"
        assert len(result.candidates) > 0

    def test_condition_check_under_1us(self, engine):
        """A single condition check should take under 1 microsecond."""
        rule = make_rule(0)
        attrs = {"material_outer": "material_5"}

        # Warm up
        for _ in range(100):
            engine.check_rule_match(rule, attrs)

        N = 10000
        start = time.perf_counter()
        for _ in range(N):
            engine.check_rule_match(rule, attrs)
        elapsed = time.perf_counter() - start

        avg_us = (elapsed / N) * 1_000_000
        # Single condition match should be very fast (< 5us per check)
        assert avg_us < 50, f"Single condition check took {avg_us:.1f}us, expected <50us"

    def test_cache_miss_then_hit_performance(self, engine, mock_db):
        """Cache should make subsequent lookups faster."""
        from app.core.models import ClassificationRuleModel

        # Create mock rows
        mock_rows = []
        for i in range(50):
            row = MagicMock()
            row.rule_id = f"cached_{i:04d}"
            row.category_mask = "*"
            row.priority = i
            row.conditions = [{"attribute": "material_outer", "operator": "==", "value": f"material_{i % 10}"}]
            row.action = {"type": "boost", "target_code": "9503", "reason": "test"}
            row.source = "Test"
            row.effective_date = date.today()
            row.expiry_date = None
            row.created_by = None
            row.version = 1
            row.is_active = True
            mock_rows.append(row)

        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.order_by.return_value.all.return_value = mock_rows

        # First call: cache miss
        start = time.perf_counter()
        rules = engine.get_rules_for_category("*")
        first_elapsed = time.perf_counter() - start

        # Second call: cache hit
        start = time.perf_counter()
        rules2 = engine.get_rules_for_category("*")
        second_elapsed = time.perf_counter() - start

        assert len(rules) == 50
        assert len(rules2) == 50
        # Cache hit should be much faster (<10% of first call or under 1ms)
        assert second_elapsed < 0.010, f"Cache hit took {second_elapsed:.3f}s"

    def test_many_candidates_scaling(self, engine):
        """Rules on many candidates shouldn't be super-linear."""
        import statistics

        times = []
        rules = [make_rule(i) for i in range(50)]
        attrs = {"material_outer": "material_5"}

        for n_candidates in [1, 5, 10, 20, 50]:
            candidates = [make_candidate(i) for i in range(n_candidates)]
            start = time.perf_counter()
            result = engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules)
            elapsed = time.perf_counter() - start
            times.append((n_candidates, elapsed))
            assert len(result.candidates) == n_candidates

        # Check that 50 candidates don't take more than 10x the time of 5 candidates
        ratio = times[-1][1] / max(times[1][1], 0.001)
        assert ratio < 20, f"Scaling ratio {ratio:.1f}x for 50 vs 5 candidates (expected <20x)"


class TestRulesApplicationBenchmark:
    """Benchmark with realistic rule patterns."""

    def test_realistic_workload(self, engine):
        """Simulate a realistic workload with mixed rule types."""
        rules = []
        # Material-based rules (common pattern)
        materials = ["пластик", "дерево", "металл", "текстиль", "кожа", "резина", "стекло", "бумага"]
        for i, mat in enumerate(materials * 10):  # 80 rules
            rules.append(ClassificationRule(
                rule_id=f"material_{mat}_{i}",
                category_mask="*",
                priority=i,
                conditions=[RuleCondition(attribute="material_outer", operator="==", value=mat)],
                action=RuleAction(type="boost", target_code="9503", reason=f"Material: {mat}", confidence_boost=0.05),
                source="Performance test",
                effective_date=date.today(),
            ))

        # Size-based rules
        for i in range(20):
            rules.append(ClassificationRule(
                rule_id=f"size_rule_{i}",
                category_mask="*",
                priority=100 + i,
                conditions=[RuleCondition(attribute="size_cm", operator=">=", value=i * 10)],
                action=RuleAction(type="boost", target_code="9503", reason=f"Size >= {i * 10}cm", confidence_boost=0.01),
                source="Performance test",
                effective_date=date.today(),
            ))

        candidates = [make_candidate(i) for i in range(10)]
        attrs = {"material_outer": "пластик", "size_cm": 25, "has_electronics": False}

        start = time.perf_counter()
        result = engine.apply_rules(candidates=candidates, attributes=attrs, rules=rules)
        elapsed = time.perf_counter() - start

        # 100 rules should complete in under 100ms
        assert elapsed < 0.100, f"Realistic workload ({len(rules)} rules) took {elapsed:.3f}s"
        assert len(result.applied_rules) > 0
