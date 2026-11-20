import './style.css'

export const metadata = {
  title: 'SwasthyaSetu',
  description: 'Local healthcare compliance workspace',
}

export default function Layout({ children }) {
  return <html lang="en"><body>{children}</body></html>
}
