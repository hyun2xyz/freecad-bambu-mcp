# Third-party notices

This project is MIT licensed; see [LICENSE](LICENSE). `uv.lock` is the dependency resolution record.

- [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp), MIT. It is a separately installed FreeCAD addon pinned by revision in the setup guide; no source is vendored.
- [paho-mqtt](https://github.com/eclipse-paho/paho.mqtt.python), Eclipse Public License 2.0 / Eclipse Distribution License 1.0. Used for Bambu LAN MQTT transport through the locked Python dependency.
- [filelock](https://github.com/tox-dev/filelock), Unlicense. Used for cross-process workflow locks.
- [pydantic](https://github.com/pydantic/pydantic), MIT. Used by configuration and job models.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), MIT. Used for stdio server integration.

The exact resolved versions are governed by `uv.lock`. Operators distributing a built wheel or application should retain the corresponding installed package metadata and these notices. Research-only repositories listed in [docs/research.md](docs/research.md) are not dependencies and their code is not copied here; their licenses were not treated as permission to vendor.
