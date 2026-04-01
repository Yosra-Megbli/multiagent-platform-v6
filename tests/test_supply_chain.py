import pytest
from unittest.mock import patch, AsyncMock

from core.state import UniversalState
from sectors.supply_chain.aggregator import aggregate
from sectors.registry import get_sector_agents, list_available_sectors


def make_state(**kwargs) -> UniversalState:
    base: UniversalState = {
        "tenant_id": "client_demo", "sector": "supply_chain",
        "input_data": {"location": "Dallas, TX", "product_id": "ICE_CREAM_VANILLA"},
        "agent_outputs": {}, "aggregated_insights": None,
        "final_decision": None, "errors": [], "status": "running",
    }
    base.update(kwargs)
    return base


def test_registry_supply_chain():
    agents = get_sector_agents("supply_chain")
    assert "weather_agent" in agents
    assert "decision_agent" in agents


def test_registry_unknown_sector():
    with pytest.raises(ValueError):
        get_sector_agents("unknown_sector")


def test_registry_empty_sector():
    with pytest.raises(NotImplementedError):
        get_sector_agents("legal")


def test_available_sectors():
    sectors = list_available_sectors()
    assert "supply_chain" in sectors
    assert "legal" not in sectors


def test_aggregator_heat_wave():
    state = make_state(agent_outputs={
        "weather_agent": {"heat_wave": True, "max_temp": 38, "avg_temp": 35, "rain_days": 0},
        "sales_agent":   {"adjusted_30_days": 42000, "weather_multiplier": 1.4},
        "production_agent": {
            "daily_capacity": 10000, "current_stock": 5000,
            "packaging_stock": 3000, "daily_demand_forecast": 1400,
            "days_of_stock": 3.5, "days_of_packaging": 2.1,
            "capacity_gap": 400, "can_meet_demand": False,
            "reorder_needed": True, "lead_time_days": 4,
        },
    })
    result = aggregate(state)
    assert result["aggregated_insights"]["urgency"] == "HIGH"
    assert "STOCK_CRITICAL" in result["aggregated_insights"]["alerts"]
    assert "HEAT_WAVE_DEMAND_SURGE" in result["aggregated_insights"]["alerts"]


def test_aggregator_normal():
    state = make_state(agent_outputs={
        "weather_agent": {"heat_wave": False, "max_temp": 22, "avg_temp": 20, "rain_days": 1},
        "sales_agent":   {"adjusted_30_days": 30000, "weather_multiplier": 1.0},
        "production_agent": {
            "daily_capacity": 10000, "current_stock": 50000,
            "packaging_stock": 40000, "daily_demand_forecast": 1000,
            "days_of_stock": 50.0, "days_of_packaging": 40.0,
            "capacity_gap": -9000, "can_meet_demand": True,
            "reorder_needed": False, "lead_time_days": 4,
        },
    })
    result = aggregate(state)
    assert result["aggregated_insights"]["urgency"] == "LOW"
    assert result["aggregated_insights"]["alerts"] == []


@pytest.mark.asyncio
async def test_full_pipeline():
    from core.orchestrator import run_analysis

    mock_sales = [{"ds": f"2024-{i:02d}-01", "y": 1000.0} for i in range(1, 13)] * 3
    mock_production = {
        "daily_capacity": 10000, "current_stock": 30000,
        "packaging_stock": 25000, "supplier_lead_time": 4,
    }

    # MEDIUM FIX: mock the correct target — core.llm._call_openai, not a stale client ref
    mock_response = ("Increase production by 40%.", {"model": "gpt-4o", "total_usd": 0.001,
                                                       "provider": "openai", "fallback_used": False,
                                                       "input_tokens": 100, "output_tokens": 50,
                                                       "input_usd": 0.0, "output_usd": 0.001})

    with patch("sectors.supply_chain.sales_agent.get_sales_history", return_value=mock_sales), \
         patch("sectors.supply_chain.production_agent.get_production_data", return_value=mock_production), \
         patch("sectors.supply_chain.weather_agent.WEATHER_API_KEY", "invalid"), \
         patch("core.llm._call_openai", new_callable=AsyncMock, return_value=mock_response):

        result = await run_analysis(
            tenant_id="client_demo",
            sector="supply_chain",
            input_data={"location": "Dallas, TX", "product_id": "ICE_CREAM_VANILLA"},
        )

    assert result["status"] in ("done", "error", "pending_human")
    assert "weather_agent" in result["agent_outputs"]
    assert "sales_agent"   in result["agent_outputs"]
