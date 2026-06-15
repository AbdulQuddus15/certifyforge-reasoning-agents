"""
Entry point for the CertifyForge Agents package.

Allows running the demo with:
    python -m certifyforge_agents
"""

import asyncio
from .demo_orchestration import main as run_demo


def main():
    print("Starting CertifyForge Reasoning Agents demo...\n")
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
