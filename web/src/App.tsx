import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ProjectsPage from "./pages/ProjectsPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import RunDetailPage from "./pages/RunDetailPage";
import ChatPage from "./pages/ChatPage";
import PipelineEditorPage from "./pages/PipelineEditorPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/pipelines" element={<PipelineEditorPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route
          path="/projects/:id/runs/:runId"
          element={<RunDetailPage />}
        />
        <Route path="/projects/:id/chat" element={<ChatPage />} />
        <Route path="/projects/:id/chat/:sessionId" element={<ChatPage />} />
      </Route>
    </Routes>
  );
}
