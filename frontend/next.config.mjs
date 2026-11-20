import { fileURLToPath } from 'node:url'

export default {
  output: 'export',
  turbopack: { root: fileURLToPath(new URL('.', import.meta.url)) },
}
