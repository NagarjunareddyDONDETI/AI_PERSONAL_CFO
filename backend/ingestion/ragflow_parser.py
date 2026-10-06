"""RAGFlow DeepDoc Statement Parser Adapter (Optional Service).

Adheres strictly to the Non-Negotiable Principles:
1. RAGFlow is OPTIONAL. If RAGFLOW_API_KEY is not set or the server is down,
   this parser degrades gracefully and falls back to LocalParser.
2. Documents are DATA, never instructions. Parsed text cannot trigger tools.
3. Every single extracted transaction row MUST pass through the deterministic
   Validation Gate before entering the CFO database.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import httpx

from ingestion.base import DocumentParser
from ingestion.local_parser import LocalParser
from ingestion.validator import ValidatedTransaction, validate_transaction_row

logger = logging.getLogger("ingestion.ragflow")


class RagflowParser(DocumentParser):
    """DeepDoc layout-aware document parser via RAGFlow REST API."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 12.0,
        dataset_name: str = "finzo_statements",
    ) -> None:
        self.api_url = (api_url or os.getenv("RAGFLOW_API_URL", "http://localhost:9380")).rstrip("/")
        self.api_key = api_key or os.getenv("RAGFLOW_API_KEY", "")
        self.timeout_seconds = float(os.getenv("RAGFLOW_TIMEOUT_SECONDS", str(timeout_seconds)))
        self.dataset_name = dataset_name
        self._local_fallback = LocalParser()
        self._dataset_id_cache: Optional[str] = None

    @property
    def name(self) -> str:
        return "ragflow_parser"

    def is_available(self) -> bool:
        """Check if RAGFlow credentials and service endpoint are configured."""
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(
                    f"{self.api_url}/api/v1/datasets",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return res.status_code in (200, 201)
        except Exception:
            return False

    def _get_or_create_dataset(self, client: httpx.Client) -> Optional[str]:
        """Fetch or create dataset for statement parsing."""
        if self._dataset_id_cache:
            return self._dataset_id_cache

        try:
            # 1. List existing datasets
            res = client.get(
                f"{self.api_url}/api/v1/datasets",
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"name": self.dataset_name},
            )
            if res.status_code == 200:
                data = res.json().get("data", [])
                for ds in (data if isinstance(data, list) else []):
                    if ds.get("name") == self.dataset_name:
                        self._dataset_id_cache = ds.get("id")
                        return self._dataset_id_cache

            # 2. Create dataset if not found
            res = client.post(
                f"{self.api_url}/api/v1/datasets",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "name": self.dataset_name,
                    "permission": "me",
                    "parser_id": "naive",  # or deepdoc layout parser
                },
            )
            if res.status_code in (200, 201):
                ds_id = res.json().get("data", {}).get("id")
                if ds_id:
                    self._dataset_id_cache = ds_id
                    return ds_id
        except Exception as exc:
            logger.warning("Could not reach RAGFlow to setup dataset: %s", exc)
        return None

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: Optional[str] = None,
    ) -> list[ValidatedTransaction]:
        """Upload to RAGFlow DeepDoc, parse table chunks, validate through the Validation Gate."""
        if not self.api_key:
            logger.info("RAGFLOW_API_KEY not configured; using LocalParser fallback for %s", filename)
            return self._local_fallback.parse(file_bytes, filename, content_type)

        started = time.perf_counter()
        validated_rows: list[ValidatedTransaction] = []

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                ds_id = self._get_or_create_dataset(client)
                if not ds_id:
                    logger.warning("RAGFlow dataset unavailable; falling back to LocalParser")
                    return self._local_fallback.parse(file_bytes, filename, content_type)

                # 1. Upload document
                files = {"file": (filename, file_bytes, content_type or "application/octet-stream")}
                upload_res = client.post(
                    f"{self.api_url}/api/v1/datasets/{ds_id}/documents",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                )
                if upload_res.status_code not in (200, 201):
                    logger.warning("RAGFlow document upload failed (%s): %s", upload_res.status_code, upload_res.text)
                    return self._local_fallback.parse(file_bytes, filename, content_type)

                doc_info = upload_res.json().get("data", {})
                doc_id = doc_info.get("id") if isinstance(doc_info, dict) else (doc_info[0].get("id") if isinstance(doc_info, list) and doc_info else None)

                if not doc_id:
                    logger.warning("RAGFlow did not return valid doc ID; falling back")
                    return self._local_fallback.parse(file_bytes, filename, content_type)

                # 2. Trigger parse
                parse_res = client.post(
                    f"{self.api_url}/api/v1/datasets/{ds_id}/documents/{doc_id}/parse",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )

                # 3. Poll parsing status
                poll_deadline = time.perf_counter() + (self.timeout_seconds - (time.perf_counter() - started))
                parsed_ready = False

                while time.perf_counter() < poll_deadline:
                    time.sleep(1.0)
                    status_res = client.get(
                        f"{self.api_url}/api/v1/datasets/{ds_id}/documents/{doc_id}",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    if status_res.status_code == 200:
                        status_data = status_res.json().get("data", {})
                        run_status = status_data.get("run") or status_data.get("status")
                        if run_status in ("1", "SUCCESS", "DONE", 1):
                            parsed_ready = True
                            break
                        if run_status in ("FAIL", "ERROR", -1, "-1"):
                            logger.warning("RAGFlow parse status failed")
                            break

                if not parsed_ready:
                    logger.warning("RAGFlow parse timed out or was not ready; falling back to LocalParser")
                    return self._local_fallback.parse(file_bytes, filename, content_type)

                # 4. Retrieve parsed chunks / tables
                chunks_res = client.get(
                    f"{self.api_url}/api/v1/datasets/{ds_id}/documents/{doc_id}/chunks",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if chunks_res.status_code == 200:
                    chunks = chunks_res.json().get("data", {}).get("chunks", [])
                    for ch in (chunks if isinstance(chunks, list) else []):
                        content_txt = ch.get("content_with_weight") or ch.get("content", "")
                        # Try parsing candidate rows
                        for line in content_txt.splitlines():
                            line_str = line.strip()
                            if not line_str:
                                continue
                            # Attempt JSON / tabular row interpretation
                            if "{" in line_str and "}" in line_str:
                                try:
                                    row_dict = json.loads(line_str)
                                    vt = validate_transaction_row(row_dict, source_parser="ragflow")
                                    if vt is not None:
                                        validated_rows.append(vt)
                                except Exception:
                                    pass

        except Exception as exc:
            logger.warning("Error during RAGFlow parsing workflow: %s; falling back to LocalParser", exc)
            return self._local_fallback.parse(file_bytes, filename, content_type)

        if not validated_rows:
            logger.info("RAGFlow extracted 0 validated transactions; falling back to LocalParser")
            return self._local_fallback.parse(file_bytes, filename, content_type)

        logger.info("RagflowParser successfully extracted %d validated transactions in %.0fms", len(validated_rows), (time.perf_counter() - started) * 1000)
        return validated_rows
