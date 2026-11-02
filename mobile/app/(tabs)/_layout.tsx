/** 하단 탭 4개 — docs/design/screens.md '하단 탭'(2026-11-02 사용자 결정): 검색 · 필터 · 내 지도 · 내 정보 */
import React from 'react';
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../src/theme';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
const TABS: { name: string; title: string; header: string; icon: IconName }[] = [
  { name: 'index', title: '검색', header: '찐맛', icon: 'search' },
  { name: 'filters', title: '필터', header: '조건 골라 찾기', icon: 'options' },
  { name: 'map', title: '내 지도', header: '내 리뷰 지도', icon: 'map' },
  { name: 'account', title: '내 정보', header: '내 정보', icon: 'person-circle' },
];

export default function TabLayout() {
  const t = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: t.colors.background },
        headerTintColor: t.colors.textPrimary,
        tabBarActiveTintColor: t.colors.primary,
        tabBarInactiveTintColor: t.colors.textSecondary,
        tabBarStyle: { backgroundColor: t.colors.background, borderTopColor: t.colors.border },
        sceneStyle: { backgroundColor: t.colors.background },
      }}
    >
      {TABS.map((tab) => (
        <Tabs.Screen
          key={tab.name}
          name={tab.name}
          options={{
            title: tab.header,
            tabBarLabel: tab.title,
            tabBarAccessibilityLabel: `${tab.title} 탭`,
            tabBarIcon: ({ color, size, focused }) => (
              <Ionicons name={(focused ? tab.icon : `${tab.icon}-outline`) as IconName} color={color} size={size} />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
