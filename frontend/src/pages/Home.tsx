import { useNavigate } from 'react-router-dom';
import PasscodeGate from '../components/PasscodeGate';

export default function Home() {
  const nav = useNavigate();
  return (
    <PasscodeGate>
      <div className="center">
        <h1>Z-Computer</h1>
        <div className="row">
          <button className="big-icon" style={{ background: '#4f46e5' }} onClick={() => nav('/studio')}>
            <span>🛠️</span>Creator
          </button>
          <button className="big-icon" style={{ background: '#059669' }} onClick={() => window.open('#/computer', '_blank')}>
            <span>🧒</span>Child
          </button>
        </div>
      </div>
    </PasscodeGate>
  );
}
