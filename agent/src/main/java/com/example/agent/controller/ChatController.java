package com.example.agent.controller;

import com.example.agent.model.Chat;
import com.example.agent.model.ChatMessage;
import com.example.agent.repository.ChatMessageRepository;
import com.example.agent.service.ChatService;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

// NEW imports for pagination
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import java.time.Instant;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/chats")
public class ChatController {

    private final ChatService chatService;
    private final ChatMessageRepository msgRepo;

    public ChatController(ChatService chatService, ChatMessageRepository msgRepo) {
        this.chatService = chatService;
        this.msgRepo = msgRepo;
    }

    // ===== Sidebar list (paged) =====
    // GET /api/chats/paged?page=0&size=30
     
@GetMapping("/paged")
public Page<Chat> paged(@RequestParam(defaultValue = "0") int page,
                        @RequestParam(defaultValue = "30") int size,
                        @RequestParam(required = false) String ceiling) {
    var sort = Sort.by(Sort.Direction.DESC, "updatedAt");
    var pr = PageRequest.of(Math.max(0, page), Math.max(1, size), sort);

    // ✅ Only freeze pages AFTER the first one
    if (page > 0 && ceiling != null && !ceiling.isBlank()) {
        return chatService.allPagedBefore(Instant.parse(ceiling), pr);
    }
    return chatService.allPaged(pr);
}

    // (Optional) Legacy endpoint returning all (kept for compatibility)
    @GetMapping
    public List<Chat> all() {
        return chatService.all();
    }

    // ===== Create (first message) =====
    @PostMapping
    public Chat createIfMissing(@RequestBody Map<String, String> body) {
        String sessionId = body.getOrDefault("sessionId", "").trim();
        String title = body.getOrDefault("title", "").trim();
        if (sessionId.isEmpty()) throw new IllegalArgumentException("sessionId required");
        return chatService.upsertOnFirstMessage(sessionId, title);
    }

    // ===== Update sidebar preview after stream =====
    @PutMapping("/{sessionId}/last")
    public Chat updateLast(@PathVariable String sessionId,
                           @RequestBody Map<String, String> body) {
        String lastMessage = body.getOrDefault("lastMessage", "");
        String title = body.getOrDefault("title", "");
        return chatService.updateLast(sessionId, lastMessage, title);
    }

    // ===== Messages =====
    @GetMapping("/{sessionId}/messages")
    public List<ChatMessage> listMessages(@PathVariable String sessionId) {
        return msgRepo.findBySessionIdOrderByCreatedAtAsc(sessionId);
    }

    @PostMapping("/{sessionId}/messages")
    public ChatMessage appendMessage(@PathVariable String sessionId,
                                     @RequestBody Map<String, String> body) {
        String role = body.getOrDefault("role", "user");
        String content = body.getOrDefault("content", "");
        ChatMessage m = new ChatMessage();
        m.setSessionId(sessionId);
        m.setRole(role);
        m.setContent(content);
        return msgRepo.save(m);
    }

    // ===== Batch delete chats (and their messages) =====
    record BatchDeleteReq(List<String> sessionIds) {}
    record BatchDeleteRes(List<String> deleted) {}

    @DeleteMapping("/batch")
    @Transactional
    public BatchDeleteRes deleteBatch(@RequestBody BatchDeleteReq req) {
        var ids = (req.sessionIds() == null) ? List.<String>of() : req.sessionIds();
        if (ids.isEmpty()) return new BatchDeleteRes(List.of());

        // delete messages first to avoid FK/orphans
        msgRepo.deleteBySessionIds(ids);
        // then delete chat shells
        chatService.deleteChatsBySessionIds(ids);
        return new BatchDeleteRes(ids);
    }
}
