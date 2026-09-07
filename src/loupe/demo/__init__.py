"""Demo assets: fetching the sample corpus, labelled defect injection, and the manifest.

Kept out of `data`, `quality`, `insights` and `api` on purpose. Nothing here runs in a request
or a rule pass — it fetches files and manufactures one, and a module that can corrupt market
data should not sit in the package that ingests it.

Nothing here touches the database either. `corpus` puts files on disk and says what should be
loaded; the loading happens through the API like any other upload, so the demo exercises the
path it is demonstrating rather than a private one beside it.
"""

from .corpus import (
    DEMO_DIR,
    ConvertedFile,
    DemoCorpus,
    DemoFile,
    InjectionPlan,
    convert_to_csv,
    prepare_demo_corpus,
    prepare_injection,
)
from .fetch import FetchFailed, FetchReport, describe_corpus, fetch_corpus
from .injection import Defect, InjectionReport, Manifest, inject, load_manifest

__all__ = [
    "DEMO_DIR",
    "ConvertedFile",
    "Defect",
    "DemoCorpus",
    "DemoFile",
    "FetchFailed",
    "FetchReport",
    "InjectionPlan",
    "InjectionReport",
    "Manifest",
    "convert_to_csv",
    "describe_corpus",
    "fetch_corpus",
    "inject",
    "load_manifest",
    "prepare_demo_corpus",
    "prepare_injection",
]
