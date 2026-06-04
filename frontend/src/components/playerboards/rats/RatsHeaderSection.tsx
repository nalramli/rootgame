import { Group, Text, Tooltip, Stack, ThemeIcon } from "@mantine/core";
import {
  IconUsers,
  IconMapPin,
  IconTower,
  IconSword,
  IconShoppingCart,
  IconTrophy,
} from "@tabler/icons-react";

interface RatsHeaderSectionProps {
  warriorsInSupply: number;
  mobsInSupply: number;
  strongholdsInSupply: number;
}

export default function RatsHeaderSection({
  warriorsInSupply,
  mobsInSupply,
  strongholdsInSupply,
}: RatsHeaderSectionProps) {
  return (
    <Group justify="space-between" align="center" px="md" mb="xs">
      <Stack gap={0}>
        <Text
          size="1.5rem"
          fw={900}
          variant="gradient"
          gradient={{ from: "#8B0000", to: "#cc3333", deg: 45 }}
          style={{ letterSpacing: "2px", fontFamily: "serif", lineHeight: 1 }}
        >
          Lord of the Hundreds
        </Text>
        <Group gap="md" mt={4}>
          <Group gap={6}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconUsers size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000">
              {warriorsInSupply} WARRIORS IN SUPPLY
            </Text>
          </Group>
          <Group gap={6}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconMapPin size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000">
              {mobsInSupply} MOBS IN SUPPLY
            </Text>
          </Group>
          <Group gap={6}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconTower size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000">
              {strongholdsInSupply} STRONGHOLDS IN SUPPLY
            </Text>
          </Group>
        </Group>
      </Stack>

      <Group gap="xl" align="center">
        <Tooltip
          label="Your warlord is a warrior that cannot be removed outside battle, moved outside your turn, or placed except with Anoint."
          multiline
          w={250}
          withArrow
          position="bottom"
        >
          <Group gap={4} style={{ cursor: "help" }}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconSword size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000" tt="uppercase">
              The Warlord
            </Text>
          </Group>
        </Tooltip>

        <Tooltip
          label="When you craft an item, gain it but score no listed points, or remove it to score them."
          multiline
          w={250}
          withArrow
          position="bottom"
        >
          <Group gap={4} style={{ cursor: "help" }}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconShoppingCart size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000" tt="uppercase">
              Contempt for Trade
            </Text>
          </Group>
        </Tooltip>

        <Tooltip
          label="At start of battle as attacker, you may say you're looting the defender. You deal no rolled hits, but they do. At end, if you rule the battle clearing, take an item from their Crafted Items."
          multiline
          w={270}
          withArrow
          position="bottom"
        >
          <Group gap={4} style={{ cursor: "help" }}>
            <ThemeIcon color="#8B0000" variant="light" size="sm">
              <IconTrophy size={14} />
            </ThemeIcon>
            <Text size="xs" fw={700} c="#8B0000" tt="uppercase">
              Looters
            </Text>
          </Group>
        </Tooltip>
      </Group>
    </Group>
  );
}
