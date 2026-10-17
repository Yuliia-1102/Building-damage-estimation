"""Gemini layers that never send a request: answers come from the cache, or from the stubs.

Used when paid calls are switched off (the UI toggle, run_testset without --gemini): a case that was
already assessed shows its real cached answers, any other case falls back to the fixed stub answers.
"""
import logging

from models.gemini_building import GeminiBuildingEstimator
from models.gemini_decision import GeminiDecisionLayer
from models.stub import StubBuildingParams, StubDecisionLayer

log = logging.getLogger(__name__)


class NotCached(RuntimeError):
    pass


class OfflineClient:
    """Stands in for genai.Client: any request that reaches it means the answer was not cached."""

    class models:
        @staticmethod
        def generate_content(**_):
            raise NotCached("answer not in the cache and Gemini calls are switched off")


class CachedOrStubBuilding:
    def __init__(self):
        self.gemini = GeminiBuildingEstimator(client=OfflineClient())
        self.stub = StubBuildingParams()
        self.last_source = None     # "cache" or "stub", shown in the UI

    def estimate(self, images, masks):
        try:
            p = self.gemini.estimate(images, masks)
            self.last_source = "cache"
            return p
        except NotCached:
            log.info("building parameters not cached, stub used")
            self.last_source = "stub"
            return self.stub.estimate(images, masks)


class CachedOrStubDecision:
    def __init__(self):
        self.gemini = GeminiDecisionLayer(client=OfflineClient(), retries=0)
        self.stub = StubDecisionLayer()
        self.last_source = None

    def decide(self, ratios, areas, building):
        try:
            d = self.gemini.decide(ratios, areas, building)
            self.last_source = "cache"
            return d
        except NotCached:
            log.info("decision not cached, stub used")
            self.last_source = "stub"
            return self.stub.decide(ratios, areas, building)
