# mcp_client.py
# Connects to my MCP server (mcp_server/server.py).
#
# The MCP library is async but Streamlit is not, so I run the MCP connection
# in a separate thread with its own event loop and send the tool calls to it.

import asyncio
import json
import os
import sys
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, server_file):
        self.server_file = server_file
        self.session = None
        self.tools = []
        self.error = None
        self.ready = threading.Event()
        self.stop_event = None

        # on windows we need ProactorEventLoop to start a subprocess
        if sys.platform == "win32":
            self.loop = asyncio.ProactorEventLoop()
        else:
            self.loop = asyncio.new_event_loop()

        thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        thread.start()

        # start the server and wait until it is connected
        asyncio.run_coroutine_threadsafe(self.connect(), self.loop)
        self.ready.wait(180)
        if self.session is None:
            raise Exception("MCP server did not start: " + str(self.error))

    async def connect(self):
        project_folder = os.path.dirname(os.path.dirname(self.server_file))
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        params = StdioServerParameters(command=sys.executable, args=[self.server_file],
                                       cwd=project_folder, env=env)
        self.stop_event = asyncio.Event()
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # get the list of tools from the server
                    result = await session.list_tools()
                    for tool in result.tools:
                        self.tools.append({
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.input_schema,
                        })

                    self.session = session
                    self.ready.set()
                    # keep the connection open until close() is called
                    await self.stop_event.wait()
        except BaseException as e:
            self.error = e
            self.ready.set()

    def call_tool(self, name, arguments=None):
        if self.session is None:
            raise Exception("MCP server is not connected")
        if arguments is None:
            arguments = {}

        future = asyncio.run_coroutine_threadsafe(self.session.call_tool(name, arguments), self.loop)
        result = future.result(600)

        text = ""
        for item in result.content:
            if item.type == "text":
                text = text + item.text

        if result.is_error:
            text = text.replace("Error executing tool " + name + ": ", "")
            raise Exception(text)
        return text

    def call_tool_json(self, name, arguments=None):
        return json.loads(self.call_tool(name, arguments))

    def close(self):
        if self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
