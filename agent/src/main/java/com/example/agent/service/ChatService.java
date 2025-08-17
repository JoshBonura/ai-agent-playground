package com.example.agent.service;

import com.example.agent.model.Chat;
import com.example.agent.repository.ChatRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import java.time.Instant;

import java.util.List;

@Service
public class ChatService {
    private final ChatRepository repo;
    public ChatService(ChatRepository repo) { this.repo = repo; }

    public Chat upsertOnFirstMessage(String sessionId, String title) {
        return repo.findBySessionId(sessionId).orElseGet(() -> {
            Chat c = new Chat();
            c.setSessionId(sessionId);
            c.setTitle((title == null || title.isBlank()) ? "New Chat" : title);
            return repo.save(c);
        });
    }

    public Page<Chat> allPaged(Pageable pageable) { return repo.findAll(pageable); }

    
public Page<Chat> allPagedBefore(Instant ceiling, Pageable pageable) {
    return repo.findAllBefore(ceiling, pageable);
}

    public Chat updateLast(String sessionId, String lastMessage, String maybeTitle) {
        Chat chat = repo.findBySessionId(sessionId)
            .orElseThrow(() -> new IllegalArgumentException("Unknown session: " + sessionId));

        if (lastMessage != null) {
            chat.setLastMessage(lastMessage);
        }
        // ← Always allow title override when provided
        if (maybeTitle != null && !maybeTitle.isBlank()) {
            chat.setTitle(maybeTitle);
        }
        return repo.save(chat);
    }
    public List<Chat> all() { return repo.findAll(); }

    @Transactional
    public void deleteChatsBySessionIds(List<String> ids) {
        if (ids == null || ids.isEmpty()) return;
        repo.deleteBySessionIds(ids);
    }
}
