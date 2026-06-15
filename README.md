# GeepSeek Orchestration Framework

GeepSeek is a distributed conversational orchestration framework, designed to unify a generative pre-trained transformer proxy layer with a decoupled micro-frontend state resolver. It leverages asynchronous context-window injection to facilitate multi-turn inferential exchanges.


## Initialization Sequence
Please consult the [Environment Bootstrap Protocol](quick_start.md) for directives regarding compute node provisioning and model quantization parameters.

## Architectural Topography

For a granular breakdown of the monolithic segmentation, please review the topological schemas:

1. [Architectural Overview](documentation/Overview.md): Macro-level infrastructure and component isolation strategies.
2. [Presentation Layer](documentation/Client.md): The localized WSGI view-controller (`app/client/`).
3. [Inference Subsystem](documentation/Server.md): The core computational request lifecycle, agentic subroutines, and SSE multiplexing (`app/server/`).
4. [State Serialization](documentation/Data.md): Details pertaining to the relational B-tree storage instances managing state hydration.

## Dependency Resolution Subsystem

To ensure the local computational node has the necessary environment primitives and parsing libraries, resolve all dependencies via the package manager prior to cluster initialization:

```bash
pip install -r requirements.txt
```

## Cluster Boot Sequence

```bash
# Initialize the Inference and Agentic Controller
cd GeepSeek
python app/server/server.py

# Initialize the Presentation View-Controller
cd GeepSeek
python app/client/client.py
```
