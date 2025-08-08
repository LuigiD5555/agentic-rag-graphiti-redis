# RAG Agentic Graphiti

**RAG Agentic Graphiti** is a hybrid Retrieval-Augmented Generation (RAG) engine combining **vector search** (Qdrant) and **graph search** (Neo4j), with **Redis caching** for faster responses. It is designed to integrate seamlessly with local Large Language Models (LLMs) via **LM Studio** using an OpenAI-compatible API.

This system is built for scenarios that require **document ingestion**, **code indexing**, and **semantic relationship mapping** between entities — enabling detailed, context-rich answers.

---

## Overview

- **Hybrid retrieval:** Combines semantic similarity search with graph-based relationship queries.
- **LM Studio integration:** Uses local embedding and language models via API endpoints.
- **Caching layer:** Speeds up repeat queries using Redis.
- **Document & code ingestion:** Processes text, markdown, and source code with automatic entity/relation extraction.
- **Socket server option:** Enables network-based queries from external clients.
- **Modular architecture:** Each service (vector store, graph store, cache, LLM) can be replaced or extended without affecting the rest of the pipeline.

---

## Requirements

- **Python** 3.11+
- **LM Studio** running locally with:
	- At least one **embedding model** loaded
	- At least one **language model** loaded
- **Docker** or **Podman** (for Qdrant, Redis, Neo4j)
- Dependencies listed in `requirements.txt`

---

## Installation

1. **Clone the repository**
2. **Create and activate a virtual environment**
3. **Install dependencies**
4. **Configure environment variables**  
	Copy the example `.env` file and adjust values:

---

## Environment Variables

---

## Starting Required Services

You can run Qdrant, Redis, and Neo4j using the provided **Podman Compose** file:

Or with Docker Compose:

---

## Usage

### Ingest Documents and Code

Supported formats:

- `.pdf`, `.docx`, `.txt`, `.md` → processed as text
- `.py`, `.js` → structural summaries (functions, classes)

During ingestion:

- Text is split into chunks
- Embeddings are generated via LM Studio
- Data is inserted into Qdrant
- Entities and relationships are extracted and inserted into Neo4j

---

### Query the RAG

**Interactive CLI mode**

**Single query**

---

### Socket Server Mode (Remote Access)

Start the server:

Connect from another machine:

---

## Integrating on Another Machine

If another machine has **LM Studio** and similar specs:

1. Clone this repository.
2. Configure `.env` with the **remote** Qdrant, Redis, and Neo4j URLs.
3. Run:
	or connect via the socket server.

> The provided `podman-compose.yml` uses `network_mode: host`, which simplifies external connections within the same network.

---

## Roadmap

- Support for additional document formats
- Custom preprocessing plugins
- Improved relation extraction with prompt templates
- Lightweight web-based query interface

---

## License

This project is **proprietary**.  
Use, copying, distribution, or modification is prohibited without explicit written permission from the author.

---

**Author:**  
José Luis López López Prieto