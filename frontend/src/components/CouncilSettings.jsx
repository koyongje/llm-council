import { useEffect, useState } from 'react';
import { api } from '../api';
import './CouncilSettings.css';

const STATUS_LABELS = {
  ok: '정상',
  credit: '크레딧 소진',
  rate_limit: '한도 초과',
  error: '오류',
  unknown: '확인 전',
};

const MIN_MEMBERS = 2;
const MAX_MEMBERS = 6;

export default function CouncilSettings({ isBusy, onClose, onSaved }) {
  const [members, setMembers] = useState([]);
  const [chairman, setChairman] = useState('');
  const [catalog, setCatalog] = useState({});
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [testResults, setTestResults] = useState({});
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getSettings()
      .then((s) => {
        setMembers(s.council_models);
        setChairman(s.chairman_model);
      })
      .catch((e) => setError(e.message));
    api.listModels()
      .then(setCatalog)
      .catch((e) => setError(e.message))
      .finally(() => setCatalogLoading(false));
  }, []);

  const allModels = Object.values(catalog).flatMap((p) => p.models || []);
  const catalogErrors = Object.entries(catalog).filter(([, p]) => p.error);

  const updateMember = (index, value) => {
    setMembers(members.map((m, i) => (i === index ? value : m)));
  };

  const cleaned = () => ({
    council: members.map((m) => m.trim()).filter(Boolean),
    chair: chairman.trim(),
  });

  const handleTest = async () => {
    const { council, chair } = cleaned();
    setTesting(true);
    setError('');
    try {
      const results = await api.testModels([...council, chair].filter(Boolean));
      setTestResults(Object.fromEntries(results.map((r) => [r.model, r])));
    } catch (e) {
      setError(e.message);
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    const { council, chair } = cleaned();
    setSaving(true);
    setError('');
    try {
      await api.saveSettings(council, chair);
      onSaved();
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const renderResult = (model) => {
    const result = testResults[model.trim()];
    if (!result) return null;
    return (
      <span className={`settings-result engine-badge engine-${result.status}`} title={result.message || ''}>
        {STATUS_LABELS[result.status] || result.status}
      </span>
    );
  };

  return (
    <div className="settings-backdrop" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <h2>위원회 설정</h2>

        <datalist id="model-options">
          {allModels.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>

        <div className="settings-section-label">위원 ({MIN_MEMBERS}–{MAX_MEMBERS}명)</div>
        {members.map((model, index) => (
          <div key={index} className="settings-row">
            <input
              list="model-options"
              value={model}
              placeholder="provider/model-id"
              onChange={(e) => updateMember(index, e.target.value)}
            />
            {renderResult(model)}
            <button
              className="settings-remove"
              onClick={() => setMembers(members.filter((_, i) => i !== index))}
              disabled={members.length <= MIN_MEMBERS}
            >
              삭제
            </button>
          </div>
        ))}
        <button
          className="settings-add"
          onClick={() => setMembers([...members, ''])}
          disabled={members.length >= MAX_MEMBERS}
        >
          + 위원 추가
        </button>

        <div className="settings-section-label">의장</div>
        <div className="settings-row">
          <input
            list="model-options"
            value={chairman}
            placeholder="provider/model-id"
            onChange={(e) => setChairman(e.target.value)}
          />
          {renderResult(chairman)}
        </div>

        <div className="settings-note">
          {catalogLoading
            ? '모델 목록을 불러오는 중…'
            : `입력칸에서 모델 ${allModels.length}개를 자동완성으로 고를 수 있습니다. 목록에 없는 id도 입력할 수 있습니다.`}
          {catalogErrors.map(([provider, p]) => (
            <div key={provider} className="settings-error">
              {provider} 목록 불러오기 실패: {p.error}
            </div>
          ))}
          <div>
            연결 확인은 짧은 질문을 한 번 보내 호출이 되는지만 봅니다(소액 과금). 웹 검색·PDF 지원은{' '}
            <code>uv run python -m backend.check_models --full</code>로 확인하세요.
          </div>
        </div>

        {error && <div className="settings-error">{error}</div>}
        {isBusy && <div className="settings-error">질문이 진행 중일 때는 저장할 수 없습니다.</div>}

        <div className="settings-actions">
          <button onClick={handleTest} disabled={testing || saving}>
            {testing ? '확인 중…' : '연결 확인'}
          </button>
          <button className="settings-save" onClick={handleSave} disabled={isBusy || saving || testing}>
            {saving ? '저장 중…' : '저장'}
          </button>
          <button onClick={onClose}>취소</button>
        </div>
      </div>
    </div>
  );
}
