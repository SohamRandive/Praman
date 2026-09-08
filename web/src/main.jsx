import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import Landing from './landing/Landing.jsx'
import './styles.css'

/* Two surfaces, one bundle.

   The console is reached at `#/console` and everything else is the landing
   page. Routing stays a piece of state read off the hash, for the same reason
   the console's own navigation is: two destinations do not need history
   integration, and a dependency added for a demo is a dependency the reader
   has to be told about. The console component is mounted exactly as it was;
   nothing about it knows this file changed. */

function useHashRoute() {
  const read = () => (window.location.hash.startsWith('#/console') ? 'console' : 'landing')
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const on = () => {
      const next = read()
      setRoute((prev) => {
        // Only a change of surface resets scroll. In-page anchors on the
        // landing page also fire hashchange, and stealing their scroll would
        // break every link in the section nav.
        if (prev !== next) window.scrollTo(0, 0)
        return next
      })
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

function Root() {
  return useHashRoute() === 'console' ? <App /> : <Landing />
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
