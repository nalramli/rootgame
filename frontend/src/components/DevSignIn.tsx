import { useContext, useEffect, useState } from "react";
import { UserContext } from "../contexts/UserProvider";
import { GameContext } from "../contexts/GameProvider";
import { FACTION_CONFIG } from "../data/factionConfig";

const FACTION_VALUE_TO_KEY: Record<
  string,
  keyof typeof FACTION_CONFIG
> = {
  ca: "cats",
  bi: "birds",
  wa: "woodland-alliance",
  cr: "crows",
  mo: "moles",
  ra: "rats",
};

export default function DevSignIn() {
  const { signInMutation: signIn, username } = useContext(UserContext);
  const { session } = useContext(GameContext);

  // status of which faction we currently think we are representing
  const [activeButton, setActiveButton] = useState<string | null>(null);

  useEffect(() => {
    if (session?.players && username) {
      const currentPlayer = session.players.find(
        (p: any) => p.username.toLowerCase() === username.toLowerCase(),
      );
      if (currentPlayer?.faction?.label) {
        setActiveButton(currentPlayer.faction.label);
      } else {
        setActiveButton(null);
      }
    }
  }, [session, username]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {(session?.players ?? []).map((player) => {
        const configKey = FACTION_VALUE_TO_KEY[player.faction.value];
        const config = configKey ? FACTION_CONFIG[configKey] : null;
        const isActive = activeButton === player.faction.label;
        return (
          <button
            key={player.faction.value}
            onClick={() => {
              signIn.mutate({ username: player.username, password: "password" });
              setActiveButton(player.faction.label);
            }}
            style={{
              background: isActive ? (config?.svgColor ?? "gray") : "white",
              color: isActive ? "white" : "black",
            }}
          >
            {player.faction.label}
          </button>
        );
      })}
    </div>
  );
}
