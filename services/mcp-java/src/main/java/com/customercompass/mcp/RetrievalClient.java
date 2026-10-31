package com.customercompass.mcp;

import java.util.Map;

/** Document search. Retrieval (embeddings and the vector store) belongs to the Python API, so this is a call to it. */
public interface RetrievalClient {

    /** The same result object the FastMCP search_documents tool returns. */
    Map<String, Object> search(String query, String companyName);
}
