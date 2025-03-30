import { useEffect, useState } from "react";
import { api } from "./api";

export function AuthGuard({ children }) {
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api
      .me()
      .then((user) => {
        if (!user) {
          window.location.href = "/auth/login";
          return;
        }
        setChecked(true);
      })
      .catch(() => {
        window.location.href = "/auth/login";
      });
  }, []);

  if (!checked) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#0d0900] text-[#d4c4a0]">
        Loading...
      </div>
    );
  }

  return children;
}
