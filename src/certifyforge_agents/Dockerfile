# Basic Dockerfile for the CertifyForge Reasoning Agents package.
# This allows containerized deployment via azd + azure.ai.agent host.
#
# The image runs the package with azure-ai-agentserver-responses (POST /responses,
# GET /readiness) so Playground Chat and azd invoke use the official protocol.

FROM python:3.12-slim

WORKDIR /app

# Copy the service contents (build context = contents of src/certifyforge_agents per azure.yaml).
# We place them under a subdirectory named after the package so that
# "python -m certifyforge_agents..." works naturally.
COPY . /app/certifyforge_agents

# Install runtime dependencies (azure ones only needed when real grounding / Search is configured).
# The core certifyforge_agents logic uses only the Python standard library.
RUN pip install --no-cache-dir -r /app/certifyforge_agents/requirements.txt && \
    python -c "import azure.identity, openai, azure.search.documents; from azure.ai.agentserver.responses import ResponsesAgentServerHost"

# Ensure the package is importable as top-level "certifyforge_agents"
ENV PYTHONPATH=/app

# Use a dedicated entrypoint script for complex startup logic.
# This avoids Dockerfile parser issues with multi-line CMD containing shell keywords.
# Copy to /app/ for simple relative exec from WORKDIR.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && sed -i 's/\r$//' /app/entrypoint.sh

# The entrypoint:
# - Optionally runs the demo on startup (for observable logs in agent monitoring).
#   Set RUN_DEMO_ON_START=0 (via env in agent.yaml or portal) to skip.
# - Then starts the readiness server.
#
# The platform probes /readiness (and /health) expecting HTTP 200 for the session to be ready.
# Without a responding server, you get "session_not_ready" timeouts.
#
# readiness_server.py uses ResponsesAgentServerHost: /readiness probes and
# POST /responses (structured orchestration vs Chat fast-path via TextResponse/SSE).
CMD ["./entrypoint.sh"]