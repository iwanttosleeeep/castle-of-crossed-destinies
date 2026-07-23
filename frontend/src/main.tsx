import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './skills.css'
import './card.css'
import './workflow.css'
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
