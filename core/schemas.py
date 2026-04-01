"""
AGENT SCHEMAS — v5
===================
LOW FIX: WeatherOutput.derive_heat_wave validator was fragile because
it depended on field declaration order in info.data.
Removed the validator — heat_wave must now be computed before
passing data to the model (done in weather_agent.py).
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class UrgencyLevel(str, Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


class WeatherOutput(BaseModel):
    avg_temp:  float = Field(..., ge=-50, le=60)
    max_temp:  float = Field(..., ge=-50, le=60)
    rain_days: int   = Field(..., ge=0,   le=30)
    heat_wave: bool                               # LOW FIX: computed before model, no fragile validator
    location:  str
    fallback:  bool  = Field(False)


class SalesOutput(BaseModel):
    baseline_daily:     float = Field(..., ge=0)
    total_30_days:      float = Field(..., ge=0)
    adjusted_30_days:   float = Field(..., ge=0)
    weather_multiplier: float = Field(..., ge=0, le=5)
    memory_adjustment:  float = Field(..., ge=0, le=5)
    final_multiplier:   float = Field(..., ge=0, le=5)
    peak_day:           Optional[str] = None
    data_source:        str  = Field("database")
    fallback:           bool = Field(False)


class ProductionOutput(BaseModel):
    daily_capacity:        int   = Field(..., ge=0)
    current_stock:         int   = Field(..., ge=0)
    packaging_stock:       int   = Field(..., ge=0)
    daily_demand_forecast: float = Field(..., ge=0)
    days_of_stock:         float = Field(..., ge=0)
    days_of_packaging:     float = Field(..., ge=0)
    capacity_gap:          float
    can_meet_demand:       bool
    reorder_needed:        bool
    lead_time_days:        int   = Field(..., ge=0)
    fallback:              bool  = Field(False)


class AggregatedInsights(BaseModel):
    alerts:             list[str]    = Field(default_factory=list)
    urgency:            UrgencyLevel = Field(UrgencyLevel.LOW)
    weather_summary:    str
    demand_summary:     str
    stock_days:         Optional[float] = None
    packaging_days:     Optional[float] = None
    capacity_gap:       Optional[float] = None
    multiplier_applied: Optional[float] = None
    has_fallback_data:  bool = Field(False)


class HITLOutput(BaseModel):
    confidence:     float = Field(..., ge=0, le=1)
    requires_human: bool
    approved:       bool
    reviewer:       Optional[str] = None
    comment:        Optional[str] = None


class LLMCostInfo(BaseModel):
    model:        str
    input_tokens:  int   = Field(..., ge=0)
    output_tokens: int   = Field(..., ge=0)
    input_usd:     float = Field(..., ge=0)
    output_usd:    float = Field(..., ge=0)
    total_usd:     float = Field(..., ge=0)


class SupplyChainInput(BaseModel):
    location:      str  = Field(..., min_length=2)
    product_id:    str  = Field(..., min_length=1)
    webhook_url:   Optional[str]  = None
    tenant_config: Optional[dict] = Field(default_factory=dict)


def validate_weather_output(data: dict) -> dict:
    # LOW FIX: compute heat_wave here, before constructing the model
    data = dict(data)
    data["heat_wave"] = data.get("max_temp", 0) > 35
    return WeatherOutput(**data).model_dump()

def validate_sales_output(data: dict) -> dict:
    return SalesOutput(**data).model_dump()

def validate_production_output(data: dict) -> dict:
    return ProductionOutput(**data).model_dump()

def validate_aggregated_insights(data: dict) -> dict:
    return AggregatedInsights(**data).model_dump()
