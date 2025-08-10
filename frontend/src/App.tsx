import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import AgentRunner from "./components/AgentRunner";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/runner" element={<AgentRunner />} />
        <Route path="*" element={<AgentRunner />} /> {/* default route */}
      </Routes>
    </Router>
  );
}