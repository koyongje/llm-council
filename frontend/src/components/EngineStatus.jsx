import './EngineStatus.css';

const LABELS = {
  ok: '정상',
  credit: '크레딧 소진',
  rate_limit: '한도 초과',
  error: '오류',
  unknown: '확인 전',
};

const BILLING_PAGES = {
  openai: 'https://platform.openai.com/settings/organization/billing/',
  anthropic: 'https://platform.claude.com/settings/billing',
  google: 'https://aistudio.google.com/billing',
};

export default function EngineStatus({ engines }) {
  if (!engines || engines.length === 0) return null;

  return (
    <div className="engine-status">
      <div className="engine-status-title">엔진 상태</div>
      {engines.map((engine) => {
        const [provider, name] = engine.model.split('/');
        const billing = BILLING_PAGES[provider];
        return (
          <div key={engine.model} className="engine-row" title={engine.message || ''}>
            <div className="engine-line">
              <span className="engine-name">{name || engine.model}</span>
              <span className={`engine-badge engine-${engine.status}`}>
                {LABELS[engine.status] || engine.status}
              </span>
            </div>
            {engine.status === 'credit' && billing && (
              <a className="engine-link" href={billing} target="_blank" rel="noreferrer">
                충전하기
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}
