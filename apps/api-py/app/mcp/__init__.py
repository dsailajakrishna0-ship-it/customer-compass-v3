"""Stage 9: MCP (Model Context Protocol) tool server + client.

`tools.py` holds the actual tool implementations (thin wrappers around the
existing crm/rag modules -- no SQL/retrieval logic is duplicated here).
`server.py` exposes them over MCP (run as a separate stdio subprocess, per
the Stage 9 design decision -- a more realistic MCP deployment shape than
running the tool server in-process). `client.py` is the MCP client used by
the chat route's tool-calling loop to spawn that subprocess, discover tools,
and invoke them.
"""
