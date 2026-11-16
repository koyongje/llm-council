import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import CouncilSettings from './components/CouncilSettings';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [sendError, setSendError] = useState('');
  const [engines, setEngines] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Phone layout only: the sidebar is a slide-in drawer (see App.css)
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Aborts the running council request (the "중지" button)
  const abortRef = useRef(null);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadEngines = async () => {
    try {
      setEngines(await api.getEngineStatus());
    } catch (error) {
      console.error('Failed to load engine status:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
    loadEngines();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
      setSidebarOpen(false);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setSidebarOpen(false);
  };

  const handleUploadFile = async (file) => {
    const id = currentConversationId;
    if (!id) return;
    const uploaded = await api.uploadFile(id, file);
    setCurrentConversation((prev) =>
      prev?.id === id
        ? { ...prev, files: [...(prev.files || []), uploaded] }
        : prev
    );
  };

  // Immutably merge `patch` into the last (in-progress assistant) message;
  // `patch.loading` is merged into the existing loading flags.
  const updateLastMessage = (patch) => {
    setCurrentConversation((prev) => {
      const messages = [...prev.messages];
      const last = messages[messages.length - 1];
      messages[messages.length - 1] = {
        ...last,
        ...patch,
        loading: { ...last.loading, ...patch.loading },
      };
      return { ...prev, messages };
    });
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    setSendError('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Set once the stream reports `complete` or `error`; if it ends without
      // either (backend crashed, connection dropped) the UI must not stay stuck.
      let finished = false;

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        if (eventType === 'complete' || eventType === 'error') finished = true;
        // Any finished stage may have changed an engine's credit/limit status
        if (eventType.endsWith('_complete') || eventType === 'complete' || eventType === 'error') {
          loadEngines();
        }
        switch (eventType) {
          case 'stage1_start':
            updateLastMessage({ loading: { stage1: true } });
            break;

          case 'stage1_complete':
            updateLastMessage({ stage1: event.data, loading: { stage1: false } });
            break;

          case 'stage2_start':
            updateLastMessage({ loading: { stage2: true } });
            break;

          case 'stage2_complete':
            updateLastMessage({
              stage2: event.data,
              metadata: event.metadata,
              loading: { stage2: false },
            });
            break;

          case 'stage3_start':
            updateLastMessage({ loading: { stage3: true } });
            break;

          case 'stage3_complete':
            updateLastMessage({ stage3: event.data, loading: { stage3: false } });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            // Drop the dead optimistic user + assistant messages
            setCurrentConversation((prev) => ({
              ...prev,
              messages: prev.messages.slice(0, -2),
            }));
            setSendError(event.message || 'The council request failed.');
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      }, controller.signal);

      if (!finished) {
        throw new Error('The connection to the server ended before the council finished.');
      }
    } catch (error) {
      const stopped = error.name === 'AbortError';
      if (!stopped) console.error('Failed to send message:', error);
      // Remove optimistic messages: the backend saved nothing for this turn
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setSendError(
        stopped
          ? '질문을 중지했습니다. 이미 진행된 모델 호출 비용은 청구될 수 있습니다.'
          : error.message || 'Failed to send message.'
      );
      setIsLoading(false);
      if (stopped) loadEngines();
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar
        engines={engines}
        onOpenSettings={() => {
          setSettingsOpen(true);
          setSidebarOpen(false);
        }}
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
      />
      <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      <div className="main-pane">
        <div className="mobile-topbar">
          <button
            className="menu-btn"
            onClick={() => setSidebarOpen(true)}
            aria-label="대화 목록 열기"
          >
            ☰
          </button>
          <span className="mobile-title">
            {currentConversation?.title || 'LLM Council'}
          </span>
        </div>
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          onStop={handleStop}
          onUploadFile={handleUploadFile}
          isLoading={isLoading}
          sendError={sendError}
        />
      </div>
      {settingsOpen && (
        <CouncilSettings
          isBusy={isLoading}
          onClose={() => setSettingsOpen(false)}
          onSaved={loadEngines}
        />
      )}
    </div>
  );
}

export default App;
