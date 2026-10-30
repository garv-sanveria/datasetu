# Generated automatically by DataSetu Engine
# DO NOT EDIT DIRECTLY - Re-generate via `datasetu sdk <file_or_url>`
"""Typed Python SDK for DataSetu Engine API (v1.0.0).

Compiled with Bharat Entity Intelligence and DuckDB columnar execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Union
import httpx


@dataclass
class Meta:
    """Pagination and sub-millisecond query execution metadata."""

    total: int
    page: int
    limit: int
    pages: int
    version: str
    query_ms: float

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Meta:
        return cls(
            total=d.get("total", 0),
            page=d.get("page", 1),
            limit=d.get("limit", 50),
            pages=d.get("pages", 1),
            version=str(d.get("version", "1.0.0")),
            query_ms=float(d.get("query_ms", 0.0)),
        )


@dataclass
class DatasetRecord:
    """Typed record representing a row in the dataset."""

    administrative_units___state_name: Optional[str] = None
    administrative_units___district_name: Optional[str] = None
    governance_portfolio___sector_category: Optional[str] = None
    governance_portfolio___national_flagship_scheme: Optional[str] = None
    financial_provisions__inr____central_sanctioned_allocation: Optional[float] = None
    financial_provisions__inr____state_matching_share_released: Optional[float] = None
    execution___audit___actual_expenditure_incurred: Optional[float] = None
    impact_metrics___beneficiaries_reached: Optional[int] = None
    audit___monitoring___performance_lifecycle_status: Optional[str] = None
    lgd_state_code: Optional[int] = None
    lgd_district_code: Optional[int] = None
    lgd_district_name: Optional[str] = None
    lgd_match_method: Optional[str] = None
    lgd_match_score: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DatasetRecord:
        return cls(
            administrative_units___state_name=data.get("Administrative Units - State Name"),
            administrative_units___district_name=data.get("Administrative Units - District Name"),
            governance_portfolio___sector_category=data.get("Governance Portfolio - Sector Category"),
            governance_portfolio___national_flagship_scheme=data.get("Governance Portfolio - National Flagship Scheme"),
            financial_provisions__inr____central_sanctioned_allocation=data.get("Financial Provisions (INR) - Central Sanctioned Allocation"),
            financial_provisions__inr____state_matching_share_released=data.get("Financial Provisions (INR) - State Matching Share Released"),
            execution___audit___actual_expenditure_incurred=data.get("Execution & Audit - Actual Expenditure Incurred"),
            impact_metrics___beneficiaries_reached=data.get("Impact Metrics - Beneficiaries Reached"),
            audit___monitoring___performance_lifecycle_status=data.get("Audit & Monitoring - Performance Lifecycle Status"),
            lgd_state_code=data.get("lgd_state_code"),
            lgd_district_code=data.get("lgd_district_code"),
            lgd_district_name=data.get("lgd_district_name"),
            lgd_match_method=data.get("lgd_match_method"),
            lgd_match_score=data.get("lgd_match_score"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Administrative Units - State Name": self.administrative_units___state_name,
            "Administrative Units - District Name": self.administrative_units___district_name,
            "Governance Portfolio - Sector Category": self.governance_portfolio___sector_category,
            "Governance Portfolio - National Flagship Scheme": self.governance_portfolio___national_flagship_scheme,
            "Financial Provisions (INR) - Central Sanctioned Allocation": self.financial_provisions__inr____central_sanctioned_allocation,
            "Financial Provisions (INR) - State Matching Share Released": self.financial_provisions__inr____state_matching_share_released,
            "Execution & Audit - Actual Expenditure Incurred": self.execution___audit___actual_expenditure_incurred,
            "Impact Metrics - Beneficiaries Reached": self.impact_metrics___beneficiaries_reached,
            "Audit & Monitoring - Performance Lifecycle Status": self.audit___monitoring___performance_lifecycle_status,
            "lgd_state_code": self.lgd_state_code,
            "lgd_district_code": self.lgd_district_code,
            "lgd_district_name": self.lgd_district_name,
            "lgd_match_method": self.lgd_match_method,
            "lgd_match_score": self.lgd_match_score,
        }


@dataclass
class DataResponse:
    """Paginated response containing typed records and query metadata."""

    data: List[DatasetRecord]
    meta: Meta

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DataResponse:
        records = [DatasetRecord.from_dict(r) for r in d.get("data", [])]
        meta = Meta.from_dict(d.get("meta", {}))
        return cls(data=records, meta=meta)


class DatasetuClient:
    """High-performance client for the compiled DataSetu REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._custom_client = client is not None
        self.client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> DatasetuClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        if not self._custom_client:
            self.client.close()

    def health(self) -> Dict[str, Any]:
        """Verify engine connectivity and active dataset health."""
        resp = self.client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def get_data(
        self,
        page: int = 1,
        limit: int = 50,
        sort: Optional[str] = None,
        fields: Optional[Union[str, List[str]]] = None,
        q: Optional[str] = None,
        **filters: Any,
    ) -> DataResponse:
        """Query paginated dataset with filters, full-text search, and field selection."""
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if sort:
            params["sort"] = sort
        if q:
            params["q"] = q
        if fields:
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields

        for k, v in filters.items():
            if v is not None:
                params[k] = v

        resp = self.client.get("/v1/data", params=params)
        resp.raise_for_status()
        return DataResponse.from_dict(resp.json())

    def iter_data(
        self,
        batch_size: int = 100,
        max_records: Optional[int] = None,
        sort: Optional[str] = None,
        fields: Optional[Union[str, List[str]]] = None,
        q: Optional[str] = None,
        **filters: Any,
    ) -> Generator[DatasetRecord, None, None]:
        """Auto-paginating generator that yields typed records sequentially."""
        current_page = 1
        yielded_count = 0
        filters.pop("limit", None)

        while True:
            resp = self.get_data(
                page=current_page,
                limit=batch_size,
                sort=sort,
                fields=fields,
                q=q,
                **filters,
            )
            for record in resp.data:
                yield record
                yielded_count += 1
                if max_records is not None and yielded_count >= max_records:
                    return

            if current_page >= resp.meta.pages or not resp.data:
                break
            current_page += 1

    def get_summary(
        self,
        group_by: Optional[str] = None,
        metric: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve dataset distribution statistics and optional metric aggregations."""
        params: Dict[str, Any] = {}
        if group_by:
            params["group_by"] = group_by
        if metric:
            params["metric"] = metric

        resp = self.client.get("/v1/data/summary", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_schema(self) -> Dict[str, Any]:
        """Fetch dynamic DuckDB column types and Pydantic schemas."""
        resp = self.client.get("/v1/schema")
        resp.raise_for_status()
        return resp.json()

    def get_report(self) -> Dict[str, Any]:
        """Fetch compilation and Bharat entity resolution report."""
        resp = self.client.get("/v1/report")
        resp.raise_for_status()
        return resp.json()

    def get_changelog(self) -> Dict[str, Any]:
        """Fetch version changelog and atomic dataset swap history."""
        resp = self.client.get("/v1/changelog")
        resp.raise_for_status()
        return resp.json()