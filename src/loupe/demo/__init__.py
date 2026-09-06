"""Demo assets: labelled defect injection and the ground-truth manifest that labels it.

Kept out of `data`, `quality`, `insights` and `api` on purpose. Nothing here runs in a request
or a rule pass — it manufactures a file for a demonstration, and a module that can corrupt
market data should not sit in the package that ingests it.
"""

from .injection import Defect, InjectionReport, Manifest, inject, load_manifest

__all__ = ["Defect", "InjectionReport", "Manifest", "inject", "load_manifest"]
