package com.example.agent.service;

import com.example.agent.model.ChatMessage;
import com.example.agent.repository.ChatMessageRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ChatMessageService {
  private final ChatMessageRepository repo;
  public ChatMessageService(ChatMessageRepository repo) { this.repo = repo; }

  @Transactional
  public ChatMessage append(String sessionId, String role, String content) {
    ChatMessage m = new ChatMessage();
    m.setSessionId(sessionId);
    m.setRole(role);
    m.setContent(content);
    return repo.save(m);
  }

  @Transactional(readOnly = true)
  public List<ChatMessage> list(String sessionId) {
    return repo.findBySessionIdOrderByCreatedAtAsc(sessionId);
  }
}
