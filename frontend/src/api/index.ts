import { http } from './client'

// ── 类型 ──────────────────────────────────────────────────────
export interface UserInfo {
  id: string
  username: string
  display_name?: string
  role: string
  age?: number
  gender?: string
}

export interface SessionInfo {
  id: string
  title: string
  chief_complaint?: string
  department?: string
  urgency: string
  status: string
  summary?: string
  message_count: number
  created_at?: string
  updated_at?: string
}

export interface MessageInfo {
  id: number
  role: string
  content: string
  meta?: Record<string, any>
  created_at?: string
}

export interface TriageInfo {
  department?: string
  urgency?: string
  red_flags?: string[]
  differential?: string[]
  recommended_tests?: string[]
  questions?: string[]
  advice?: string
  rationale?: string
  safety_level?: string
}

export interface Citation {
  case_id: number
  hospital?: string
  department?: string
  disease?: string
  snippet?: string
  similarity?: number
  source_url?: string
}

export interface ChatResult {
  session_id: string
  answer: string
  answer_mode: string
  urgency: string
  citations: Citation[]
  followups: string[]
  confidence: number
  coverage: string
  safety?: { level: string; flags: string[]; advice: string; disclaimer?: string }
  disclaimer: string
}

export interface RecordInfo {
  id: number
  session_id: string
  chief_complaint?: string
  present_illness?: string
  past_history?: string
  allergy_history?: string
  physical_exam?: string
  assessment?: string
  plan?: string
  diagnosis?: string
  status: string
  soap?: Record<string, any>
  created_at?: string
  updated_at?: string
}

export interface CaseItem {
  case_id: number
  hospital: string
  department: string
  disease: string
  snippet: string
  help_wanted?: string
}

export interface StatsInfo {
  cases: number
  qa_pairs: number
  chunks: number
  departments: number
  users: number
  sessions: number
  records: number
}

// ── 接口 ──────────────────────────────────────────────────────
export const authApi = {
  async login(username: string, password: string) {
    const { data } = await http.post('/auth/login', { username, password })
    return data as { access_token: string; token_type: string; user: UserInfo }
  },
  async register(payload: {
    username: string
    password: string
    display_name?: string
    age?: number
    gender?: string
  }) {
    const { data } = await http.post('/auth/register', payload)
    return data as { access_token: string; token_type: string; user: UserInfo }
  },
  async me() {
    const { data } = await http.get('/auth/me')
    return data as UserInfo
  },
}

export const sessionApi = {
  async create(payload: { title?: string; chief_complaint?: string }) {
    const { data } = await http.post('/sessions', payload)
    return data as { session: SessionInfo; messages: MessageInfo[]; triage: TriageInfo | null; has_record: boolean }
  },
  async list() {
    const { data } = await http.get('/sessions')
    return data as SessionInfo[]
  },
  async detail(id: string) {
    const { data } = await http.get(`/sessions/${id}`)
    return data as { session: SessionInfo; messages: MessageInfo[]; triage: TriageInfo | null; has_record: boolean }
  },
  async rename(id: string, title: string) {
    const { data } = await http.patch(`/sessions/${id}`, { title })
    return data as SessionInfo
  },
  async remove(id: string) {
    await http.delete(`/sessions/${id}`)
  },
  async messages(id: string) {
    const { data } = await http.get(`/sessions/${id}/messages`)
    return data as MessageInfo[]
  },
}

export const chatApi = {
  async send(payload: { session_id: string; message: string; department?: string; enable_retrieval?: boolean }) {
    const { data } = await http.post('/chat', payload)
    return data as ChatResult
  },
}

export const triageApi = {
  async create(payload: {
    chief_complaint: string
    age?: number
    gender?: string
    duration?: string
    session_id?: string
  }) {
    const { data } = await http.post('/triage', payload)
    return data as TriageInfo
  },
  async bySession(sessionId: string) {
    const { data } = await http.get(`/triage/${sessionId}`)
    return (data?.triage ?? null) as TriageInfo | null
  },
}

export const recordApi = {
  async generate(sessionId: string) {
    const { data } = await http.post('/records/generate', { session_id: sessionId })
    return data as RecordInfo
  },
  async list() {
    const { data } = await http.get('/records')
    return data as RecordInfo[]
  },
  async bySession(sessionId: string) {
    const { data } = await http.get(`/records/by-session/${sessionId}`)
    return data as RecordInfo
  },
  async update(id: number, payload: Partial<RecordInfo>) {
    const { data } = await http.put(`/records/${id}`, payload)
    return data as RecordInfo
  },
}

export const caseApi = {
  async search(params: { keyword?: string; department?: string; page?: number; page_size?: number }) {
    const { data } = await http.get('/cases', { params })
    return data as { total: number; page: number; page_size: number; items: CaseItem[] }
  },
  async semantic(params: { q: string; department?: string; top_k?: number }) {
    const { data } = await http.get('/cases/semantic', { params })
    return data as { query: string; confidence: number; coverage: string; cases: any[] }
  },
  async departments(limit = 30) {
    const { data } = await http.get('/cases/departments', { params: { limit } })
    return data as { department: string; count: number }[]
  },
  async detail(caseId: number) {
    const { data } = await http.get(`/cases/${caseId}`)
    return data as any
  },
}

export const systemApi = {
  async stats() {
    const { data } = await http.get('/system/stats')
    return data as StatsInfo
  },
  async info() {
    const { data } = await http.get('/system/info')
    return data as any
  },
}
