import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { IonicModule } from '@ionic/angular';

import { LogoComponent } from './logo.component';
import { PhotoComponent } from './photo.component';
import { AvatarComponent } from './avatar.component';
import { AffinityBadgeComponent, AffinityRingComponent } from './affinity.component';
import { AuthLayoutComponent } from './auth-layout.component';

const DECLARED = [
  LogoComponent, PhotoComponent, AvatarComponent, AffinityBadgeComponent, AffinityRingComponent, AuthLayoutComponent,
];

@NgModule({
  imports: [CommonModule, FormsModule, RouterModule, IonicModule],
  declarations: DECLARED,
  exports: [...DECLARED, CommonModule, FormsModule, RouterModule, IonicModule],
})
export class SharedModule {}
