import os

import golem_mcp.motion  # noqa: F401 - importing registers its tools on the shared server
import golem_mcp.server  # noqa: F401 - importing registers its tools on the shared server
from golem_mcp.app import mcp

mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("GOLEM_MCP_PORT", "9786")))
