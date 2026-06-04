import { useContext } from "react";
import { ClearingContext } from "./Clearing";
import { WarriorTroop } from "./WarriorTroop";
import { type FactionLabel } from "../../utils/factionUtils";
import { Tooltip } from "@mantine/core";

export const WarriorSlot = ({
  x,
  y,
  size,
  warriorInfo,
  tooltip,
}: {
  x: number;
  y: number;
  size: number;
  warriorInfo: { faction: FactionLabel; count: number; hasWarlord?: boolean } | null;
  tooltip?: string;
}) => {
  const ctx = useContext(ClearingContext);
  if (!ctx) throw new Error("Clearing must be nested inside Circle");

  const { cx, cy, r } = ctx;
  const absSize = size * r; // relative to radius
  const absX = cx + x * r - absSize / 2;
  const absY = cy + y * r - absSize / 2;

  return (
    <Tooltip label={tooltip} disabled={!tooltip} openDelay={0} withArrow>
      <g>
        <rect
          x={absX}
          y={absY}
          width={absSize}
          height={absSize}
          stroke="none"
          fill="none"
        />
        {warriorInfo && warriorInfo.count > 0 && (
          <WarriorTroop
            x={absX}
            y={absY}
            size={absSize}
            count={warriorInfo.count}
            faction={warriorInfo.faction}
            hasWarlord={warriorInfo.hasWarlord}
          />
        )}
      </g>
    </Tooltip>
  );
};
