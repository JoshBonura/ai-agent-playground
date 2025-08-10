interface Agent {
  id: number;
  name: string;
}

interface Page<T> {
  content: T[];
  // optionally other fields like totalPages, totalElements, etc.
}

const BASE_URL = "http://localhost:8080/api/agents";

export async function getAgents(): Promise<Page<Agent>> {
  const res = await fetch(BASE_URL);
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

export async function generateAgentResponse(agentId: number, prompt: string) {
  const res = await fetch(`http://localhost:8080/api/agents/${agentId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt })
  });

  if (!res.ok) {
    throw new Error(`Error: ${res.status}`);
  }

  // Force raw text response
  return await res.text();
}                                                                        

