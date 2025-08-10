package com.example.agent.controller;

import com.example.agent.model.Agent;
import com.example.agent.service.AgentService;
import com.example.agent.service.AiService;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/agents")
@CrossOrigin(origins = "http://localhost:3000")
public class AgentController {

    private final AgentService agentService;
    private final AiService aiService;

    public AgentController(AgentService agentService, AiService aiService) {
        this.agentService = agentService;
        this.aiService = aiService;
    }

    @PostMapping("/{id}/generate")
    public ResponseEntity<String> generateAgentResponse(
            @PathVariable Long id,
            @RequestBody Map<String, String> body) {

        String prompt = body.get("prompt");
        if (prompt == null || prompt.trim().isEmpty()) {
            return ResponseEntity.badRequest().body("Prompt cannot be null or empty");
        }

        try {
            String aiResponse = aiService.generateResponse(prompt);
            return ResponseEntity.ok(aiResponse);
        } catch (Exception e) {
            e.printStackTrace();
            return ResponseEntity.status(500).body("AI request failed: " + e.getMessage());
        }
    }

    @GetMapping("/{id}")
    public ResponseEntity<Agent> getAgentById(@PathVariable Long id) {
        Optional<Agent> agent = agentService.getAgentById(id);
        return agent.map(ResponseEntity::ok).orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping
    public ResponseEntity<Page<Agent>> getAllAgents(Pageable pageable) {
        return ResponseEntity.ok(agentService.getAllAgents(pageable));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteAgent(@PathVariable Long id) {
        agentService.deleteAgent(id);
        return ResponseEntity.noContent().build();
    }

    @PostMapping
    public ResponseEntity<Agent> createAgent(@RequestBody Agent agent) {
        return ResponseEntity.ok(agentService.saveAgent(agent));
    }
}
