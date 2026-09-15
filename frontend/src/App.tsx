import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';
import Studio from './pages/Studio';
import Computer from './pages/Computer';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/studio/:appId" element={<Studio />} />
        <Route path="/computer" element={<Computer />} />
      </Routes>
    </BrowserRouter>
  );
}
