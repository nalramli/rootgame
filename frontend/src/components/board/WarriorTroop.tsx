import EquilateralTriangle from "../EquilateralTriangle";
import { type FactionLabel } from "../../utils/factionUtils";
import { factionToColor } from "../../utils/factionColors";
import flagUrl from "../../assets/flag-svgrepo-com.svg";

export const WarriorTroop = ({
  x,
  y,
  size,
  count,
  faction,
  hasWarlord = false,
}: {
  x: number;
  y: number;
  size: number;
  count: number;
  faction: FactionLabel;
  hasWarlord?: boolean;
}) => {
  const color = factionToColor(faction);
  // Anchor: top-right corner of the warrior slot box.
  // Change flagSize to resize the flag — it grows outward from the anchor.
  const flagSize = size * 0.8;
  const flagAnchorX = x + size * 0.9;
  const flagAnchorY = y + size * 0.05;
  return (
    <>
      <EquilateralTriangle
        cx={x + size / 2}
        cy={y + size / 2}
        r={size / 2}
        stroke={color}
        fill={color}
      />

      <text
        x={x + size / 2}
        y={y + size * 0.75}
        fontSize={size * 0.75}
        textAnchor="middle"
        stroke="white"
      >
        {count}
      </text>

      {hasWarlord && (
        <>
          <defs>
            <filter id={`flag-color-${faction}`}>
              <feFlood floodColor={color} floodOpacity="1" result="colorFill" />
              <feComposite in="colorFill" in2="SourceAlpha" operator="in" />
            </filter>
          </defs>
          <image
            href={flagUrl}
            x={flagAnchorX - flagSize / 2}
            y={flagAnchorY - flagSize / 2}
            width={flagSize}
            height={flagSize}
            filter={`url(#flag-color-${faction})`}
          />
        </>
      )}
    </>
  );
};
