import axios from 'axios'
import i18n from '../i18n'

// Create axios instance. In production the frontend and backend share one origin.
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 300000, // 5 minutes; ontology generation may take longer
  headers: {
    'Content-Type': 'application/json'
  }
})

service.interceptors.request.use(
  config => {
    config.headers['Accept-Language'] = i18n.global.locale.value
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

service.interceptors.response.use(
  response => {
    const res = response.data

    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      return Promise.reject(new Error(res.error || res.message || 'Error'))
    }

    return res
  },
  error => {
    console.error('Response error:', error)
    const apiError = error.response?.data?.error || error.response?.data?.message

    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timeout')
    }

    if (error.message === 'Network Error') {
      console.error('Network error - please check your connection')
    }

    if (typeof apiError === 'string' && apiError) {
      error.message = apiError
    }

    return Promise.reject(error)
  }
)

export default service
