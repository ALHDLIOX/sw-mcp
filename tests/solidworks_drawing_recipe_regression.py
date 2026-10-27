"""Opt-in native SW regression: generate a recipe through MCP and fetch its PDF.

Example: python tests/solidworks_drawing_recipe_regression.py --model C:\\parts\\PEEK_CONNECTING_BRACKET.SLDPRT --out-dir C:\\deliveries\\recipe-regression --version 2024
Requires the matching native model and an installed/licensed SW; not collected by pytest.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    model = args.model.resolve()
    output = args.out_dir.resolve()
    before = hashlib.sha256(model.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "SW_MCP_OUTPUT_ROOT": str(output),
        "SW_MCP_QUEUE_DIR": str(output / ".ledger"),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp-server/server.py")],
        env=env,
        cwd=str(ROOT),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=300)
        ) as session,
    ):
        await session.initialize()
        response = await session.call_tool(
            "solidworks_generate_drawing_from_recipe",
            {
                "params": {
                    "recipe_path": str(args.recipe.resolve()),
                    "source_model": str(model),
                    "output_dir": str(output),
                    "version": args.version,
                }
            },
        )
        result = json.loads(next(c.text for c in response.content if c.type == "text"))
        if result.get("status") != "pass":
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        pdf_ref = next(
            item for item in result["artifact_refs"] if item["name"].endswith(".pdf")
        )
        resource = await session.read_resource(pdf_ref["uri"])
        data = base64.b64decode(resource.contents[0].blob)
        if hashlib.sha256(data).hexdigest() != pdf_ref["sha256"]:
            raise RuntimeError("MCP artifact round-trip hash mismatch")
    if hashlib.sha256(model.read_bytes()).hexdigest() != before:
        raise RuntimeError("Source model was modified")
    evidence = {
        "status": "pass",
        "transport": "MCP stdio",
        "source_unchanged": True,
        "native_dimension_count": len(result["reopened_dimension_values_mm"]),
        "pdf_dimension_matches": len(
            result["review"]["pdf_dimension_rendering"]["matched"]
        ),
        "pdf_artifact_roundtrip_sha256": pdf_ref["sha256"],
        "artifact_count": len(result["artifact_refs"]),
        "outputs": result["outputs"],
    }
    (output / "mcp_regression.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--recipe", type=Path, default=ROOT / "examples/peek_bracket_drawing.json"
    )
    parser.add_argument("--version", type=int, default=2024)
    asyncio.run(run(parser.parse_args()))
