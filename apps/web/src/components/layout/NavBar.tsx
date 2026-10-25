import { NavLink } from "react-router-dom";

/** Top-level page navigation between the company dashboard and the chat assistant. */
export function NavBar() {
  return (
    <nav className="nav-bar">
      <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
        Dashboard
      </NavLink>
      <NavLink to="/chat" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
        Ask Compass
      </NavLink>
    </nav>
  );
}
