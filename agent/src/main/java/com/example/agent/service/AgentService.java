package com.example.agent.service;

import com.example.agent.model.Agent;
import com.example.agent.repository.AgentRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
public class AgentService {

    private final AgentRepository agentRepository;

    public AgentService(AgentRepository agentRepository) {
        this.agentRepository = agentRepository;
    }

    public Agent saveAgent(Agent agent) {
        return agentRepository.save(agent);
    }

    public Optional<Agent> getAgentById(Long id) {
        return agentRepository.findById(id);
    }

    public Page<Agent> getAllAgents(Pageable pageable) {
        return agentRepository.findAll(pageable);
    }

    public void deleteAgent(Long id) {
        agentRepository.deleteById(id);
    }
}
