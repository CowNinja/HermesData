"""Quick role-play test using Navy batch metadata (Session 6)."""

from datetime import datetime

def navy_career_twin_response(doc: dict) -> str:
    """Simulate Jeff's voice as Navy Career Twin."""
    name = doc.get("filename", "document")
    domains = ", ".join(doc.get("twin_domains", []))
    sensitivity = ", ".join(doc.get("sensitivity_tags", []))
    
    return (
        f"This {name} is a clear piece of evidence from my Navy service. "
        f"It carries strong signals for {domains}. "
        f"Sensitivity: {sensitivity}. "
        "These kinds of records (financial footprints tied to service, VA coverage, "
        "medical disclosure forms) are exactly the kind of material that belongs in the "
        "Navy Career Twin — they show the real-world continuation of service obligations "
        "and benefits after I left active duty. Precise, factual, and part of the permanent record."
    )

if __name__ == "__main__":
    sample = {
        "filename": "2018 - NavyFCU 1099-INT statement Spencer Bloom (2 Pages).pdf",
        "twin_domains": ["Navy_Career", "Military_Service"],
        "sensitivity_tags": ["military", "financial"]
    }
    print("=== Navy Career Twin Role-Play (Session 6) ===")
    print(navy_career_twin_response(sample))
