import service from './index'

// Graph data is expensive to read from Zep (it fetches all nodes and edges).
// Keep a short client-side cache so the simulation view does not repeatedly
// hit the same graph while the UI is polling. This also prevents overlapping
// requests when a previous graph read is still in flight.
const GRAPH_CACHE_TTL_MS = 90000
const graphCache = new Map()

/**
 * 生成本体（上传文档和模拟需求）
 * @param {Object} data - 包含files, simulation_requirement, project_name等
 * @returns {Promise}
 */
export function generateOntology(formData) {
  return service({
    url: '/api/graph/ontology/generate',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

/**
 * 构建图谱
 * @param {Object} data - 包含project_id, graph_name等
 * @returns {Promise}
 */
export function buildGraph(data) {
  return service({
    url: '/api/graph/build',
    method: 'post',
    data
  })
}

/**
 * 查询任务状态
 * @param {String} taskId - 任务ID
 * @returns {Promise}
 */
export function getTaskStatus(taskId) {
  return service({
    url: `/api/graph/task/${taskId}`,
    method: 'get'
  })
}

/**
 * 获取图谱数据
 *
 * Zep graph reads return the complete node + edge set, so repeated polling
 * can consume the API rate limit quickly. Cache the latest result briefly and
 * reuse an in-flight request for the same graph.
 *
 * @param {String} graphId - 图谱ID
 * @returns {Promise}
 */
export function getGraphData(graphId) {
  if (!graphId) {
    return Promise.reject(new Error('graphId is required'))
  }

  const now = Date.now()
  const cached = graphCache.get(graphId)

  if (cached) {
    if (cached.promise) {
      return cached.promise
    }

    if (now - cached.timestamp < GRAPH_CACHE_TTL_MS) {
      return Promise.resolve(cached.data)
    }
  }

  const promise = service({
    url: `/api/graph/data/${graphId}`,
    method: 'get'
  })
    .then(result => {
      graphCache.set(graphId, {
        data: result,
        timestamp: Date.now(),
        promise: null
      })
      return result
    })
    .catch(error => {
      // Do not poison the cache after a transient Zep/network failure.
      graphCache.delete(graphId)
      throw error
    })

  graphCache.set(graphId, {
    data: null,
    timestamp: now,
    promise
  })

  return promise
}

/**
 * Limpa o cache de um grafo específico ou de todos os grafos.
 * Útil quando o usuário solicita uma atualização explícita após uma mudança.
 * @param {String} graphId - gráfico específico; omitido para limpar todos
 */
export function clearGraphDataCache(graphId) {
  if (graphId) {
    graphCache.delete(graphId)
  } else {
    graphCache.clear()
  }
}

/**
 * 获取项目信息
 * @param {String} projectId - 项目ID
 * @returns {Promise}
 */
export function getProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'get'
  })
}
