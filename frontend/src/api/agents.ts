interface Agent {
  id: number;
  name: string;
}

interface Page<T> {
  content: T[];
  // optionally other fields like totalPages, totalElements, etc.
}

const BASE_URL = "https://1c772e4eab90.ngrok-free.app/api/agents"; // your ngrok URL

export async function getAgents(): Promise<Page<Agent>> {
  const res = await fetch(BASE_URL);
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

export async function generateAgentResponse(agentId: number, prompt: string) {
  const res = await fetch(`${BASE_URL}/${agentId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt })
  });

  if (!res.ok) {
    throw new Error(`Error: ${res.status}`);
  }

  return await res.text();
}
