# Project Requirements

[Back to README](../README.md)

## Assignment goal

Build a multi-agent system that uses MCP to receive a software description and requirements through a UI and generate a complete application, including executable code and corresponding executable test cases.

## Required components

| Component | Requirements |
| --- | --- |
| Multi-agent system | Define agent roles, available tools, and collaboration patterns. Use MCP for agent communication and include the required servers, clients, and tooling. |
| User interface | Accept a software description and requirements; return executable application code and corresponding executable test cases. |
| LLM usage tracking | Track and report the number of LLM API calls and total tokens used. |

The UI above belongs to AI Coder. The selected application's UI is part of the generated output.

## Implementation instructions

- Select one software description from the class Google Sheet; each description can be chosen by only one group.
- Define its requirements and provide them as input to the multi-agent system.
- Discuss those requirements with the TA during the in-class presentation and demo.
- Collaborate as a group to design and implement the system. No template code is provided.

The selected demonstration application is **Music Playlist Mixer**: users select genres and a mood, generate playlists with smooth transitions, and save or export them. Its finalized requirements will be supplied as generation input.

## Scope to agree on

The generation workflow should accept product requirements as input. The technology stack is decided (see the [architecture decisions](./architecture.md#decisions)): the generated application is plain HTML/CSS/JavaScript tested with `node --test`. The supplied assignment does not explicitly require demonstrations of multiple applications or support for arbitrary software.

## Demo deliverables

- The submitted software description and requirements.
- Agent roles, tool access, collaboration design, and working MCP integration.
- A UI that accepts the input and returns generated code and tests.
- The generated application and corresponding tests, with commands to execute them.
- An LLM usage report showing API call count and total tokens used.


## Demo Description

The Music Playlist Mixer is an entertainment software application that allows users to create unique and personalized music playlists by combining songs from different genres. Users can select their favorite genres and set the desired mood of the playlist (such as relaxing, energetic, or romantic). The software will then analyze the selected genres and create a playlist that seamlessly transitions between the chosen genres, providing a dynamic and enjoyable listening experience. Users can save and export their playlists to share with friends or listen to them anytime.