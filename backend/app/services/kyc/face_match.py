"""Selfie vs identity-document portrait.

Providers (KYC_FACE_PROVIDER):
  none         no automatic comparison. The case is flagged and the reviewer compares the photos by eye.
  rekognition  AWS Rekognition CompareFaces: a purpose-built face model. Recommended for production.
  llm          asks the vision LLM whether the two portraits show the same person. Convenient for a hackathon demo,
               but a general model is NOT a certified biometric matcher. Treat the score as a hint for the reviewer.

Whatever the provider, the score is one input among many, and a human makes the final call.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import Settings
from app.services.kyc.extractor import DocumentExtractor, _num, content_block


class FaceMatcher(Protocol):
    async def compare(self, id_image: bytes, selfie_image: bytes) -> float | None: ...


class NoFaceMatcher:
    async def compare(self, id_image: bytes, selfie_image: bytes) -> float | None:
        return None


class LlmFaceMatcher:
    def __init__(self, extractor: DocumentExtractor) -> None:
        self._x = extractor

    async def compare(self, id_image: bytes, selfie_image: bytes) -> float | None:
        prompt = (
            "Image 1 is an identity document; image 2 is a selfie. Judge ONLY whether the portrait on the document and the "
            "person in the selfie appear to be the same person, allowing for age and lighting differences. "
            'Reply with JSON: {"same_person_likelihood": <number 0 to 1>}.'
        )
        raw = await self._x.ask(prompt, [content_block(id_image, "image/jpeg"), content_block(selfie_image, "image/jpeg")])
        return _num(raw.get("same_person_likelihood"), 0.0, 1.0)


class RekognitionFaceMatcher:
    def __init__(self, region: str) -> None:
        import boto3  # pip install .[rekognition]

        self._client = boto3.client("rekognition", region_name=region)

    async def compare(self, id_image: bytes, selfie_image: bytes) -> float | None:
        def call() -> float | None:
            result = self._client.compare_faces(SourceImage={"Bytes": selfie_image}, TargetImage={"Bytes": id_image},
                                                SimilarityThreshold=0)
            matches = result.get("FaceMatches") or []
            return max((m["Similarity"] for m in matches), default=0.0) / 100.0

        try:
            return await asyncio.to_thread(call)
        except Exception:  # noqa: BLE001  (no face found, throttling...) -> reviewer decides
            return None


def get_face_matcher(settings: Settings, extractor: DocumentExtractor) -> FaceMatcher:
    if settings.kyc_face_provider == "llm" and extractor.available:
        return LlmFaceMatcher(extractor)
    if settings.kyc_face_provider == "rekognition":
        return RekognitionFaceMatcher(settings.s3_region)
    return NoFaceMatcher()
