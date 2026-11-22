"""Observe one public example company; never load owner or broker data."""

import json

from providers.company_report_provider import CompanyReportProvider


def main():
    result = CompanyReportProvider().get("INDUSTOWER")
    print(
        json.dumps(
            {
                "symbol": "INDUSTOWER",
                "status": result["status"],
                "source": result.get("source"),
                "source_url": result.get("source_url"),
                "observed_metric_fields": sorted(result.get("metrics", {})),
                "annual_periods": len(result.get("annual", [])),
                "quarterly_periods": len(result.get("quarterly", [])),
                "shareholding_periods": len(result.get("shareholding", [])),
                "owner_data_used": False,
                "broker_orders_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
