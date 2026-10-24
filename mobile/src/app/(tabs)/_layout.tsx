import { NativeTabs } from 'expo-router/native-tabs';

import { C } from '@/components/ui';

export default function TabsLayout() {
  return (
    <NativeTabs backgroundColor="#FFFFFF" indicatorColor={C.primarySoft} labelStyle={{ selected: { color: C.primary } }}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Acasă</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="house.fill" md="home" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="scan">
        <NativeTabs.Trigger.Label>Factură</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="doc.text.viewfinder" md="document_scanner" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="prognoza">
        <NativeTabs.Trigger.Label>Prognoză</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="sun.max.fill" md="wb_sunny" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="alerte">
        <NativeTabs.Trigger.Label>Alerte</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="bell.fill" md="notifications" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="cont">
        <NativeTabs.Trigger.Label>Cont</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="person.crop.circle" md="account_circle" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
